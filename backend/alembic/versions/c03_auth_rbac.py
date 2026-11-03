"""C-03 auth/RBAC: `user.password_changed_at` + auditoría inmutable `auth_event`.

Revision ID: c03_auth_rbac
Revises: c02_core_models

Regla dura 3: una única revisión por change. Excepción acotada a la regla 11
(aprobada en C-02, reutilizada aquí): la tabla `auth_event` y sus índices son
objetos nuevos (invisibles hasta el commit) y `password_changed_at` es un
`ADD COLUMN` nullable sin default (metadata-only en PG11+, no reescribe la
tabla). Se agrega `UNIQUE (clinic_id, id)` a `user` porque la FK compuesta de
`auth_event` necesita una clave única referenciable: `user` guarda solo personal
de la clínica (decenas de filas), por lo que el `ALTER` es breve; en producción
se ejecuta en ventana de baja actividad.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c03_auth_rbac"
down_revision: str | None = "c02_core_models"
branch_labels: str | None = None
depends_on: str | None = None

UUID = postgresql.UUID(as_uuid=True)
GEN_UUID = sa.text("gen_random_uuid()")
NOW = sa.text("now()")

AUTH_EVENT_TYPES = (
    "login_success",
    "login_failed",
    "refresh_reuse_detected",
    "logout",
    "password_changed",
    "user_created",
    "user_updated",
    "user_deactivated",
    "role_changed",
)

AUTH_EVENT_TYPE = postgresql.ENUM(*AUTH_EVENT_TYPES, name="auth_event_type", create_type=False)

_TRIGGER_FN = """
CREATE FUNCTION auth_event_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'auth_event es append-only: % no permitido', TG_OP
    USING ERRCODE = 'integrity_constraint_violation';
END;
$$
"""


def upgrade() -> None:
    AUTH_EVENT_TYPE.create(op.get_bind(), checkfirst=False)

    # Metadata-only: columna nullable sin default (no reescribe la tabla).
    op.add_column(
        "user", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True)
    )

    # Clave única referenciable por la FK compuesta de auth_event.
    op.create_unique_constraint(op.f("uq_user_clinic_id_id"), "user", ["clinic_id", "id"])

    op.create_table(
        "auth_event",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("clinic_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=True),
        sa.Column("actor_user_id", UUID, nullable=True),
        sa.Column("event", AUTH_EVENT_TYPE, nullable=False),
        sa.Column("subject_hash", sa.Text(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_event")),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinic.id"], name=op.f("fk_auth_event_clinic_id_clinic")
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "user_id"],
            ["user.clinic_id", "user.id"],
            name=op.f("fk_auth_event_clinic_id_user_id_user"),
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "actor_user_id"],
            ["user.clinic_id", "user.id"],
            name=op.f("fk_auth_event_clinic_id_actor_user_id_user"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) IN ('object', 'array')",
            name=op.f("ck_auth_event_payload_is_json"),
        ),
    )
    op.create_index(
        op.f("ix_auth_event_clinic_id_created_at"), "auth_event", ["clinic_id", "created_at"]
    )
    op.create_index(
        op.f("ix_auth_event_user_id_created_at"), "auth_event", ["user_id", "created_at"]
    )

    # Inmutabilidad impuesta por la base, independiente de los privilegios del rol.
    op.execute(_TRIGGER_FN)
    op.execute(
        "CREATE TRIGGER trg_auth_event_no_mutate BEFORE UPDATE OR DELETE ON auth_event "
        "FOR EACH ROW EXECUTE FUNCTION auth_event_immutable()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_auth_event_no_mutate ON auth_event")
    op.execute("DROP FUNCTION IF EXISTS auth_event_immutable()")
    op.drop_index(op.f("ix_auth_event_user_id_created_at"), table_name="auth_event")
    op.drop_index(op.f("ix_auth_event_clinic_id_created_at"), table_name="auth_event")
    op.drop_table("auth_event")
    AUTH_EVENT_TYPE.drop(op.get_bind(), checkfirst=False)
    op.drop_constraint(op.f("uq_user_clinic_id_id"), "user", type_="unique")
    op.drop_column("user", "password_changed_at")
