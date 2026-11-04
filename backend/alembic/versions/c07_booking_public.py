"""C-07 booking-publico: `appointment.manage_token_hash` (token de gestión del paciente).

Revision ID: c07_booking_public
Revises: c13_event_slot

Regla dura 3: una única revisión por change.

Regla dura 11 (`appointment` puede tener filas):
- `ADD COLUMN manage_token_hash bytea` nullable y sin default: metadata-only.
- Los dos CHECK se agregan `NOT VALID` y luego `VALIDATE CONSTRAINT`. Si hubiera turnos
  `online` previos sin hash la validación falla explícitamente (hoy no existen: no había
  endpoint público); la migración NO inventa hashes.
- El índice único parcial se crea `CONCURRENTLY` fuera de transacción.

Solo se guarda el SHA-256 del token (32 bytes); el token en claro nunca toca la base.

Downgrade: quita índice, restricciones y columna. Los hashes se pierden: los links de
gestión ya emitidos dejan de servir.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c07_booking_public"
down_revision: str | None = "c13_event_slot"
branch_labels: str | None = None
depends_on: str | None = None

_INDEX = "uq_appointment_manage_token_hash"
_CHECKS = {
    "ck_appointment_manage_token_hash_length": (
        "CHECK (manage_token_hash IS NULL OR octet_length(manage_token_hash) = 32)"
    ),
    "ck_appointment_online_has_manage_token": (
        "CHECK (origin <> 'online' OR manage_token_hash IS NOT NULL)"
    ),
}


def upgrade() -> None:
    # 1. Columna nullable (metadata-only).
    op.add_column("appointment", sa.Column("manage_token_hash", postgresql.BYTEA(), nullable=True))

    # 2. CHECKs: NOT VALID → VALIDATE.
    for nombre, definicion in _CHECKS.items():
        op.execute(f"ALTER TABLE appointment ADD CONSTRAINT {nombre} {definicion} NOT VALID")
    for nombre in _CHECKS:
        op.execute(f"ALTER TABLE appointment VALIDATE CONSTRAINT {nombre}")

    # 3. Índice único parcial sin bloquear escrituras (fuera de transacción).
    with op.get_context().autocommit_block():
        op.execute(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
            f"WHERE c.relname = '{_INDEX}' AND NOT i.indisvalid) THEN "
            f"DROP INDEX {_INDEX}; END IF; END $$"
        )
        op.execute(
            f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX} "
            "ON appointment (manage_token_hash) WHERE manage_token_hash IS NOT NULL"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
    # SQL directo: `op.drop_constraint` re-aplicaría la naming convention al nombre.
    for nombre in _CHECKS:
        op.execute(f"ALTER TABLE appointment DROP CONSTRAINT IF EXISTS {nombre}")
    op.drop_column("appointment", "manage_token_hash")
