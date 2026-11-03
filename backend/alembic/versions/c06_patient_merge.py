"""C-06 patient-merge: fusión asistida de pacientes duplicados (puntero + auditoría append-only).

Revision ID: c06_patient_merge
Revises: c05_appointments_core

Regla dura 3: una única revisión por change.

Regla dura 11 (`patient` tiene datos):
- `merged_into_patient_id` es `ADD COLUMN` nullable sin default: metadata-only.
- La FK compuesta `(merged_into_patient_id, clinic_id) → patient(id, clinic_id)`
  (usa el UNIQUE `uq_patient_id_clinic_id` de C-05) y los CHECKs se agregan
  `NOT VALID` (lock breve, sin escanear) y luego `VALIDATE CONSTRAINT` (lock
  liviano que no bloquea escrituras).
- `patient_merge` es tabla nueva y vacía: constraints e índice junto con ella.

Downgrade: elimina `patient_merge` (se pierde la auditoría de fusiones, ver
README) y la columna; los fusionados quedan archivados sin el puntero.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c06_patient_merge"
down_revision: str | None = "c05_appointments_core"
branch_labels: str | None = None
depends_on: str | None = None

UUID = postgresql.UUID(as_uuid=True)

_FK_MERGED = "fk_patient_merged_into_patient_id_clinic_id_patient"
_CHECKS = {
    "ck_patient_not_merged_into_self": "merged_into_patient_id <> id",
    "ck_patient_merged_is_archived": "merged_into_patient_id IS NULL OR archived_at IS NOT NULL",
}

_TRIGGER_FN = """
CREATE FUNCTION patient_merge_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'patient_merge es append-only: % no permitido', TG_OP
    USING ERRCODE = 'integrity_constraint_violation';
END;
$$
"""


def upgrade() -> None:
    # 1. Puntero de fusión en `patient` (metadata-only) + FK y CHECKs NOT VALID → VALIDATE.
    op.add_column("patient", sa.Column("merged_into_patient_id", UUID, nullable=True))
    op.execute(
        f"ALTER TABLE patient ADD CONSTRAINT {_FK_MERGED} "
        "FOREIGN KEY (merged_into_patient_id, clinic_id) "
        "REFERENCES patient (id, clinic_id) NOT VALID"
    )
    for nombre, condicion in _CHECKS.items():
        op.execute(f"ALTER TABLE patient ADD CONSTRAINT {nombre} CHECK ({condicion}) NOT VALID")
    for nombre in (_FK_MERGED, *_CHECKS):
        op.execute(f"ALTER TABLE patient VALIDATE CONSTRAINT {nombre}")

    # 2. Auditoría append-only de fusiones.
    op.create_table(
        "patient_merge",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("clinic_id", UUID, nullable=False),
        sa.Column("source_patient_id", UUID, nullable=False),
        sa.Column("target_patient_id", UUID, nullable=False),
        sa.Column("actor_user_id", UUID, nullable=False),
        sa.Column("appointment_ids", postgresql.JSONB(), nullable=False),
        sa.Column("filled_fields", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_patient_merge")),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinic.id"], name=op.f("fk_patient_merge_clinic_id_clinic")
        ),
        sa.ForeignKeyConstraint(
            ["source_patient_id", "clinic_id"],
            ["patient.id", "patient.clinic_id"],
            name=op.f("fk_patient_merge_source_patient_id_clinic_id_patient"),
        ),
        sa.ForeignKeyConstraint(
            ["target_patient_id", "clinic_id"],
            ["patient.id", "patient.clinic_id"],
            name=op.f("fk_patient_merge_target_patient_id_clinic_id_patient"),
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "actor_user_id"],
            ["user.clinic_id", "user.id"],
            name=op.f("fk_patient_merge_clinic_id_actor_user_id_user"),
        ),
        sa.CheckConstraint(
            "source_patient_id <> target_patient_id",
            name=op.f("ck_patient_merge_distinct_patients"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(appointment_ids) = 'array' AND jsonb_typeof(filled_fields) = 'array'",
            name=op.f("ck_patient_merge_payload_are_arrays"),
        ),
    )
    op.create_index(
        op.f("ix_patient_merge_clinic_id_created_at"), "patient_merge", ["clinic_id", "created_at"]
    )
    op.execute(_TRIGGER_FN)
    op.execute(
        "CREATE TRIGGER trg_patient_merge_no_mutate BEFORE UPDATE OR DELETE "
        "ON patient_merge FOR EACH ROW EXECUTE FUNCTION patient_merge_immutable()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_patient_merge_no_mutate ON patient_merge")
    op.execute("DROP FUNCTION IF EXISTS patient_merge_immutable()")
    op.drop_table("patient_merge")
    # SQL directo: `op.drop_constraint` re-aplicaría la naming convention al nombre.
    for nombre in (*_CHECKS, _FK_MERGED):
        op.execute(f"ALTER TABLE patient DROP CONSTRAINT IF EXISTS {nombre}")
    op.drop_column("patient", "merged_into_patient_id")
