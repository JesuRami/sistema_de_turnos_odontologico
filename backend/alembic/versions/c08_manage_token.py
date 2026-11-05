"""C-08 gestion-por-token: `clinic.contact_phone` (teléfono de derivación público).

Revision ID: c08_manage_token
Revises: c07_booking_public

Regla dura 3: una única revisión por change.

Regla dura 11 (`clinic` tiene filas):
- `ADD COLUMN contact_phone text` nullable y sin default: metadata-only.
- El CHECK se agrega `NOT VALID` y luego `VALIDATE CONSTRAINT`; `ADD
  CONSTRAINT … NOT VALID` no toma lock de tabla.
- Sin índices: `contact_phone` no se filtra ni se ordena.

Solo se guarda un E.164 ya normalizado por la capa de aplicación; la base
defiende el largo como última barrera.

Downgrade: quita el CHECK y la columna. El teléfono cargado se pierde.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "c08_manage_token"
down_revision: str | None = "c07_booking_public"
branch_labels: str | None = None
depends_on: str | None = None

_CHECK = "ck_clinic_contact_phone_length"
_CHECK_DEF = "CHECK (contact_phone IS NULL OR char_length(contact_phone) BETWEEN 6 AND 32)"


def upgrade() -> None:
    op.add_column("clinic", sa.Column("contact_phone", sa.Text(), nullable=True))
    op.execute(f"ALTER TABLE clinic ADD CONSTRAINT {_CHECK} {_CHECK_DEF} NOT VALID")
    op.execute(f"ALTER TABLE clinic VALIDATE CONSTRAINT {_CHECK}")


def downgrade() -> None:
    op.execute(f"ALTER TABLE clinic DROP CONSTRAINT IF EXISTS {_CHECK}")
    op.drop_column("clinic", "contact_phone")
