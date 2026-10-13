"""Revisión base vacía C-01 (DDL listo para EXCLUDE en C-05).

Revision ID: c01_base
Revises: None (primera revisión del proyecto).
"""

revision: str = "c01_base"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Base vacía intencional: C-01 no crea tablas (modelos en C-02).
    pass


def downgrade() -> None:
    pass
