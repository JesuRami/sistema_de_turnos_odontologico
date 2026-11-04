"""C-13 reportes-admin-export: instantánea del turno en `appointment_event` + `data_exported`.

Revision ID: c13_event_slot
Revises: c06_patient_merge

Regla dura 3: una única revisión por change.

Regla dura 11 (`appointment_event` puede tener filas):
- Las cuatro columnas nuevas son `ADD COLUMN` nullable sin default: metadata-only.
  Los eventos previos quedan con NULL (la tabla es inmutable: un UPDATE de backfill
  lo rechaza el trigger, y no se desactiva).
- Las FK compuestas intra-tenant (regla 4) y el CHECK de coherencia se agregan
  `NOT VALID` y luego `VALIDATE CONSTRAINT`.
- El índice `(clinic_id, slot_starts_at)` se crea `CONCURRENTLY` fuera de
  transacción.
- `ALTER TYPE auth_event_type ADD VALUE` tampoco corre en transacción.

Downgrade: quita índice, restricciones y columnas. El valor `data_exported` del
enum NO se puede quitar sin recrear el tipo: queda en la base (inofensivo).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c13_event_slot"
down_revision: str | None = "c06_patient_merge"
branch_labels: str | None = None
depends_on: str | None = None

UUID = postgresql.UUID(as_uuid=True)

_INDEX = "ix_appointment_event_clinic_id_slot_starts_at"
_FKS = {
    "fk_appointment_event_clinic_id_professional_id_professional": (
        "FOREIGN KEY (clinic_id, professional_id) REFERENCES professional (clinic_id, id)"
    ),
    "fk_appointment_event_clinic_id_chair_id_chair": (
        "FOREIGN KEY (clinic_id, chair_id) REFERENCES chair (clinic_id, id)"
    ),
}
_CHECK = "ck_appointment_event_slot_coherent"
_CHECK_SQL = (
    "CHECK ((slot_starts_at IS NULL AND slot_ends_at IS NULL "
    "AND professional_id IS NULL AND chair_id IS NULL) "
    "OR (slot_starts_at IS NOT NULL AND slot_ends_at IS NOT NULL "
    "AND professional_id IS NOT NULL AND chair_id IS NOT NULL "
    "AND slot_ends_at > slot_starts_at))"
)


def upgrade() -> None:
    # 1. Columnas nullable (metadata-only).
    op.add_column(
        "appointment_event", sa.Column("slot_starts_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "appointment_event", sa.Column("slot_ends_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("appointment_event", sa.Column("professional_id", UUID, nullable=True))
    op.add_column("appointment_event", sa.Column("chair_id", UUID, nullable=True))

    # 2. FKs compuestas y CHECK: NOT VALID → VALIDATE.
    for nombre, definicion in _FKS.items():
        op.execute(f"ALTER TABLE appointment_event ADD CONSTRAINT {nombre} {definicion} NOT VALID")
    op.execute(f"ALTER TABLE appointment_event ADD CONSTRAINT {_CHECK} {_CHECK_SQL} NOT VALID")
    for nombre in (*_FKS, _CHECK):
        op.execute(f"ALTER TABLE appointment_event VALIDATE CONSTRAINT {nombre}")

    # 3. Índice sin bloquear escrituras y valor nuevo del enum (fuera de transacción).
    with op.get_context().autocommit_block():
        op.execute(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
            f"WHERE c.relname = '{_INDEX}' AND NOT i.indisvalid) THEN "
            f"DROP INDEX {_INDEX}; END IF; END $$"
        )
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX} "
            "ON appointment_event (clinic_id, slot_starts_at)"
        )
        op.execute("ALTER TYPE auth_event_type ADD VALUE IF NOT EXISTS 'data_exported'")


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
    # SQL directo: `op.drop_constraint` re-aplicaría la naming convention al nombre.
    for nombre in (_CHECK, *_FKS):
        op.execute(f"ALTER TABLE appointment_event DROP CONSTRAINT IF EXISTS {nombre}")
    for columna in ("chair_id", "professional_id", "slot_ends_at", "slot_starts_at"):
        op.drop_column("appointment_event", columna)
