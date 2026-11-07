"""C-11 timeline-recordatorios: auditoría de reenvíos manuales y marcador en el job.

Revision ID: c11_reminder_timeline
Revises: c10_whatsapp_channel

Regla dura 3: una única revisión por change.

Regla dura 11 (`reminder_job` tiene filas):
- `ADD COLUMN reminder_job.manual_resend_at timestamptz` nullable y sin default: metadata-only.
- El índice parcial `ix_reminder_job_failed` se crea `CONCURRENTLY` en un `autocommit_block`, al
  final, después de todo lo transaccional. Un índice inválido de un intento previo se elimina antes
  de recrearlo.
- `reminder_manual_resend` es una tabla nueva y vacía: índices, FKs y CHECK nacen con ella.

`reminder_manual_resend` es append-only (trigger, regla 7) y no guarda datos del paciente
(regla 13).

Downgrade: elimina el índice, la tabla con su trigger y la columna. Los jobs reenviados conservan
su estado operativo; se pierde el histórico de reenvíos.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c11_reminder_timeline"
down_revision: str | None = "c10_whatsapp_channel"
branch_labels: str | None = None
depends_on: str | None = None

UUID = postgresql.UUID(as_uuid=True)
GEN_UUID = sa.text("gen_random_uuid()")
NOW = sa.text("now()")

_FAILED_INDEX = "ix_reminder_job_failed"
_FAILED_DEF = "ON reminder_job (clinic_id, scheduled_for) WHERE status = 'failed'"

_TRIGGER_FN = """
CREATE FUNCTION reminder_manual_resend_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'reminder_manual_resend es append-only: % no permitido', TG_OP
    USING ERRCODE = 'integrity_constraint_violation';
END;
$$
"""


def upgrade() -> None:
    # 1. Marcador del último reenvío manual (nullable, sin rewrite).
    op.add_column(
        "reminder_job",
        sa.Column("manual_resend_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 2. Auditoría de reenvíos (append-only).
    op.create_table(
        "reminder_manual_resend",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("clinic_id", UUID, nullable=False),
        sa.Column("appointment_id", UUID, nullable=False),
        sa.Column("reminder_job_id", UUID, nullable=False),
        sa.Column("actor_user_id", UUID, nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reminder_manual_resend")),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinic.id"], name=op.f("fk_reminder_manual_resend_clinic_id_clinic")
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "appointment_id"],
            ["appointment.clinic_id", "appointment.id"],
            name="fk_reminder_manual_resend_appointment",
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "reminder_job_id"],
            ["reminder_job.clinic_id", "reminder_job.id"],
            name="fk_reminder_manual_resend_job",
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "actor_user_id"],
            ["user.clinic_id", "user.id"],
            name="fk_reminder_manual_resend_actor",
        ),
        sa.CheckConstraint(
            "note IS NULL OR char_length(note) <= 200",
            name=op.f("ck_reminder_manual_resend_note_length"),
        ),
    )
    op.create_index(
        "ix_reminder_manual_resend_job",
        "reminder_manual_resend",
        ["clinic_id", "reminder_job_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_reminder_manual_resend_appointment",
        "reminder_manual_resend",
        ["clinic_id", "appointment_id", sa.text("created_at DESC")],
    )
    op.execute(_TRIGGER_FN)
    op.execute(
        "CREATE TRIGGER trg_reminder_manual_resend_no_mutate BEFORE UPDATE OR DELETE "
        "ON reminder_manual_resend FOR EACH ROW EXECUTE FUNCTION reminder_manual_resend_immutable()"
    )

    # 3. Índice parcial sobre una tabla con filas, sin bloquear escrituras (fuera de transacción).
    with op.get_context().autocommit_block():
        op.execute(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
            f"WHERE c.relname = '{_FAILED_INDEX}' AND NOT i.indisvalid) THEN "
            f"DROP INDEX {_FAILED_INDEX}; END IF; END $$"
        )
        op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_FAILED_INDEX} {_FAILED_DEF}")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_FAILED_INDEX}")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_reminder_manual_resend_no_mutate ON reminder_manual_resend"
    )
    op.execute("DROP FUNCTION IF EXISTS reminder_manual_resend_immutable()")
    op.drop_table("reminder_manual_resend")
    op.drop_column("reminder_job", "manual_resend_at")
