"""C-10 whatsapp-webhook: número por clínica, entrantes y outbox de respuestas.

Revision ID: c10_whatsapp_channel
Revises: c09_reminder_engine

Regla dura 3: una única revisión por change.

Regla dura 11 (`clinic` y `reminder_job` tienen filas):
- `ADD COLUMN clinic.whatsapp_phone_number_id text` nullable y sin default: metadata-only.
- Su CHECK de formato se agrega `NOT VALID` y luego `VALIDATE CONSTRAINT`.
- Los dos únicos parciales (`clinic.whatsapp_phone_number_id`,
  `reminder_job.provider_message_id`) se crean `CONCURRENTLY` en un `autocommit_block`, al final,
  después de todo lo transaccional (el bloque confirma la transacción en curso). Un índice
  inválido de un intento previo se elimina antes de recrearlo.
- `whatsapp_inbound` y `whatsapp_outbound_reply` son tablas nuevas y vacías: índices, FKs y CHECKs
  nacen con la tabla.

`whatsapp_inbound` es append-only (trigger, regla 7). Ninguna tabla guarda teléfono ni texto
(regla 13).

Downgrade: elimina índices, tablas, trigger, enums, CHECK y columna. Los `consent` de fuente
`whatsapp_reply` quedan (son historial válido de C-09).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c10_whatsapp_channel"
down_revision: str | None = "c09_reminder_engine"
branch_labels: str | None = None
depends_on: str | None = None

UUID = postgresql.UUID(as_uuid=True)
GEN_UUID = sa.text("gen_random_uuid()")
NOW = sa.text("now()")
CLOCK = sa.text("clock_timestamp()")

WHATSAPP_INTENT = postgresql.ENUM(
    "confirm", "change", "stop", "unknown", name="whatsapp_intent", create_type=False
)
WHATSAPP_REPLY_KIND = postgresql.ENUM(
    "confirmed",
    "change_link",
    "change_contact",
    "inactive",
    "ambiguous",
    "stop_ack",
    name="whatsapp_reply_kind",
    create_type=False,
)
WHATSAPP_REPLY_STATUS = postgresql.ENUM(
    "pending",
    "sending",
    "sent",
    "failed",
    "expired",
    "skipped",
    name="whatsapp_reply_status",
    create_type=False,
)
_ENUMS = (WHATSAPP_INTENT, WHATSAPP_REPLY_KIND, WHATSAPP_REPLY_STATUS)

_CHECK = "ck_clinic_whatsapp_phone_number_id_format"
_CHECK_DEF = (
    "CHECK (whatsapp_phone_number_id IS NULL OR whatsapp_phone_number_id ~ '^[0-9]{5,32}$')"
)
_CONCURRENT = {
    "uq_clinic_whatsapp_phone_number_id": (
        "ON clinic (whatsapp_phone_number_id) WHERE whatsapp_phone_number_id IS NOT NULL"
    ),
    "uq_reminder_job_provider_message_id": (
        "ON reminder_job (provider_message_id) WHERE provider_message_id IS NOT NULL"
    ),
}

_TRIGGER_FN = """
CREATE FUNCTION whatsapp_inbound_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'whatsapp_inbound es append-only: % no permitido', TG_OP
    USING ERRCODE = 'integrity_constraint_violation';
END;
$$
"""


def upgrade() -> None:
    bind = op.get_bind()
    for tipo in _ENUMS:
        tipo.create(bind, checkfirst=False)

    # 1. Número propio por clínica: columna nullable + CHECK NOT VALID → VALIDATE.
    op.add_column("clinic", sa.Column("whatsapp_phone_number_id", sa.Text(), nullable=True))
    op.execute(f"ALTER TABLE clinic ADD CONSTRAINT {_CHECK} {_CHECK_DEF} NOT VALID")
    op.execute(f"ALTER TABLE clinic VALIDATE CONSTRAINT {_CHECK}")

    # 2. Entrantes procesados (append-only).
    op.create_table(
        "whatsapp_inbound",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("clinic_id", UUID, nullable=False),
        sa.Column("provider_message_id", sa.Text(), nullable=False),
        sa.Column("phone_number_id", sa.Text(), nullable=False),
        sa.Column("patient_id", UUID, nullable=True),
        sa.Column("appointment_id", UUID, nullable=True),
        sa.Column("intent", WHATSAPP_INTENT, nullable=False),
        sa.Column("routed_by", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=CLOCK, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_whatsapp_inbound")),
        sa.UniqueConstraint(
            "clinic_id",
            "provider_message_id",
            name=op.f("uq_whatsapp_inbound_clinic_id_provider_message_id"),
        ),
        sa.UniqueConstraint("clinic_id", "id", name=op.f("uq_whatsapp_inbound_clinic_id_id")),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinic.id"], name=op.f("fk_whatsapp_inbound_clinic_id_clinic")
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "patient_id"],
            ["patient.clinic_id", "patient.id"],
            name=op.f("fk_whatsapp_inbound_clinic_id_patient_id_patient"),
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "appointment_id"],
            ["appointment.clinic_id", "appointment.id"],
            name=op.f("fk_whatsapp_inbound_clinic_id_appointment_id_appointment"),
        ),
        sa.CheckConstraint(
            "routed_by IN ('context', 'phone')", name=op.f("ck_whatsapp_inbound_routed_by")
        ),
        sa.CheckConstraint(
            "btrim(provider_message_id) <> ''",
            name=op.f("ck_whatsapp_inbound_provider_message_id_not_blank"),
        ),
    )
    op.create_index(
        "ix_whatsapp_inbound_clinic_patient_received",
        "whatsapp_inbound",
        ["clinic_id", "patient_id", sa.text("received_at DESC")],
    )
    op.execute(_TRIGGER_FN)
    op.execute(
        "CREATE TRIGGER trg_whatsapp_inbound_no_mutate BEFORE UPDATE OR DELETE "
        "ON whatsapp_inbound FOR EACH ROW EXECUTE FUNCTION whatsapp_inbound_immutable()"
    )

    # 3. Outbox de respuestas de sesión.
    op.create_table(
        "whatsapp_outbound_reply",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("clinic_id", UUID, nullable=False),
        sa.Column("inbound_id", UUID, nullable=False),
        sa.Column("patient_id", UUID, nullable=False),
        sa.Column("appointment_id", UUID, nullable=True),
        sa.Column("kind", WHATSAPP_REPLY_KIND, nullable=False),
        sa.Column(
            "status", WHATSAPP_REPLY_STATUS, server_default=sa.text("'pending'"), nullable=False
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_whatsapp_outbound_reply")),
        sa.UniqueConstraint(
            "inbound_id", "kind", name=op.f("uq_whatsapp_outbound_reply_inbound_id_kind")
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinic.id"], name=op.f("fk_whatsapp_outbound_reply_clinic_id_clinic")
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "inbound_id"],
            ["whatsapp_inbound.clinic_id", "whatsapp_inbound.id"],
            name="fk_whatsapp_outbound_reply_inbound",
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "patient_id"],
            ["patient.clinic_id", "patient.id"],
            name=op.f("fk_whatsapp_outbound_reply_clinic_id_patient_id_patient"),
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "appointment_id"],
            ["appointment.clinic_id", "appointment.id"],
            name="fk_whatsapp_outbound_reply_appointment",
        ),
        sa.CheckConstraint(
            "attempts >= 0", name=op.f("ck_whatsapp_outbound_reply_attempts_nonneg")
        ),
        sa.CheckConstraint(
            "status <> 'sending' OR claimed_at IS NOT NULL",
            name=op.f("ck_whatsapp_outbound_reply_sending_has_claim"),
        ),
        sa.CheckConstraint(
            "status <> 'sent' OR sent_at IS NOT NULL",
            name=op.f("ck_whatsapp_outbound_reply_sent_has_sent_at"),
        ),
        sa.CheckConstraint(
            "char_length(last_error) <= 64",
            name=op.f("ck_whatsapp_outbound_reply_last_error_code"),
        ),
    )
    op.create_index(
        "ix_whatsapp_outbound_reply_due",
        "whatsapp_outbound_reply",
        ["available_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_whatsapp_outbound_reply_claimed",
        "whatsapp_outbound_reply",
        ["claimed_at"],
        postgresql_where=sa.text("status = 'sending'"),
    )

    # 4. Únicos parciales sobre tablas con filas, sin bloquear escrituras (fuera de transacción).
    with op.get_context().autocommit_block():
        for nombre, definicion in _CONCURRENT.items():
            op.execute(
                "DO $$ BEGIN "
                "IF EXISTS (SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                f"WHERE c.relname = '{nombre}' AND NOT i.indisvalid) THEN "
                f"DROP INDEX {nombre}; END IF; END $$"
            )
            op.execute(f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {nombre} {definicion}")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for nombre in _CONCURRENT:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {nombre}")
    bind = op.get_bind()
    op.drop_table("whatsapp_outbound_reply")
    op.execute("DROP TRIGGER IF EXISTS trg_whatsapp_inbound_no_mutate ON whatsapp_inbound")
    op.execute("DROP FUNCTION IF EXISTS whatsapp_inbound_immutable()")
    op.drop_table("whatsapp_inbound")
    # SQL directo: `op.drop_constraint` re-aplicaría la naming convention al nombre.
    op.execute(f"ALTER TABLE clinic DROP CONSTRAINT IF EXISTS {_CHECK}")
    op.drop_column("clinic", "whatsapp_phone_number_id")
    for tipo in reversed(_ENUMS):
        tipo.drop(bind, checkfirst=False)
