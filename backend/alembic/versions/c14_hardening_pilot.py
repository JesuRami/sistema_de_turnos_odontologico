"""C-14 hardening-piloto: rol `app_writer` y umbral mensual de costo de WhatsApp.

Revision ID: c14_hardening_pilot
Revises: c12_waiting_list

Regla dura 3: una única revisión por change.

- **Rol `app_writer`** (D7, diferido de C-05): `SELECT, INSERT, UPDATE` en tablas operativas,
  `SELECT, INSERT` en las append-only, ningún `DELETE`, y `DEFAULT PRIVILEGES` para lo que creen
  migraciones futuras. El SQL vive en `app.ops.db_privileges` (sin dependencias, también para
  `psql`). Los roles son del cluster: se crea solo si no existe. El usuario de login lo crea
  `python -m app.ops.db_roles` con la clave del entorno, nunca esta migración.
- **`clinic.whatsapp_monthly_alert_micros`** (D8, SU-07): `BIGINT` nullable sin default
  (metadata-only sobre una tabla con filas) y `CHECK > 0` con `NOT VALID` → `VALIDATE`
  (regla 11). NULL = sin alerta.

Downgrade: revoca los privilegios de esta base y elimina el rol solo si ninguna otra base lo
referencia (si no, queda con un NOTICE); quita la columna y su CHECK.
"""

import sqlalchemy as sa
from alembic import op
from app.ops.db_privileges import APP_ROLE, grant_statements, revoke_statements

revision: str = "c14_hardening_pilot"
down_revision: str | None = "c12_waiting_list"
branch_labels: str | None = None
depends_on: str | None = None

_ALERT_CHECK = "ck_clinic_whatsapp_monthly_alert_positive"  # naming_convention de `Base`


def upgrade() -> None:
    op.add_column(
        "clinic", sa.Column("whatsapp_monthly_alert_micros", sa.BigInteger(), nullable=True)
    )
    op.execute(
        f"ALTER TABLE clinic ADD CONSTRAINT {_ALERT_CHECK} "
        "CHECK (whatsapp_monthly_alert_micros IS NULL OR whatsapp_monthly_alert_micros > 0) "
        "NOT VALID"
    )
    op.execute(f"ALTER TABLE clinic VALIDATE CONSTRAINT {_ALERT_CHECK}")
    # Al final: los privilegios cubren también la columna recién agregada.
    for sentencia in grant_statements():
        op.execute(sentencia)


def downgrade() -> None:
    existe = op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :rol"), {"rol": APP_ROLE}
    )
    if existe.scalar() is not None:
        for sentencia in revoke_statements():
            op.execute(sentencia)
    op.execute(f"ALTER TABLE clinic DROP CONSTRAINT IF EXISTS {_ALERT_CHECK}")
    op.drop_column("clinic", "whatsapp_monthly_alert_micros")
