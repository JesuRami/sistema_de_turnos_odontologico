"""C-04 agenda-config: anti-solape de `schedule_rule`, políticas, `block` y su auditoría.

Revision ID: c04_agenda_config
Revises: c03_auth_rbac

Regla dura 3: una única revisión por change.

Regla dura 11:
- `clinic`: las columnas nuevas son `ADD COLUMN … DEFAULT <constante>`
  (metadata-only en PG11+, no reescribe) y sus CHECK se agregan `NOT VALID` y
  luego se validan con `VALIDATE CONSTRAINT` (lock liviano).
- **Excepción acotada**: PostgreSQL no admite `NOT VALID` ni `CONCURRENTLY` para
  un constraint `EXCLUDE`; `ADD CONSTRAINT … EXCLUDE` toma `ACCESS EXCLUSIVE`
  sobre `schedule_rule` mientras construye su índice gist. Se acepta porque es
  una tabla de configuración (decenas de filas por clínica) y el sistema está
  pre-piloto. Si ya hubiera reglas solapadas la migración falla (fail-fast) en
  vez de dejar datos inconsistentes; en producción, ventana de baja actividad.
- `block` y `agenda_config_event` son tablas nuevas: sus índices se crean junto
  con la tabla, invisibles hasta el commit (criterio de C-02/C-03).

`btree_gist` es una extensión *trusted* desde PG13: alcanza con ser owner de la
base. El downgrade no la elimina (puede usarla `appointment` en C-05).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c04_agenda_config"
down_revision: str | None = "c03_auth_rbac"
branch_labels: str | None = None
depends_on: str | None = None

UUID = postgresql.UUID(as_uuid=True)
GEN_UUID = sa.text("gen_random_uuid()")
NOW = sa.text("now()")

BLOCK_REASON = postgresql.ENUM(
    "vacaciones",
    "feriado",
    "mantenimiento",
    "reunion",
    "otro",
    name="block_reason",
    create_type=False,
)
CONFIG_ENTITY = postgresql.ENUM(
    "professional",
    "chair",
    "schedule_rule",
    "block",
    "clinic_policy",
    name="config_entity",
    create_type=False,
)
CONFIG_ACTION = postgresql.ENUM(
    "created",
    "updated",
    "deactivated",
    "reactivated",
    "removed",
    name="config_action",
    create_type=False,
)

_EXCLUDE_SCHEDULE_RULE = """
ALTER TABLE schedule_rule ADD CONSTRAINT ex_schedule_rule_no_overlap
  EXCLUDE USING gist (
    clinic_id WITH =,
    professional_id WITH =,
    chair_id WITH =,
    weekday WITH =,
    tsrange(DATE '2000-01-01' + start_time, DATE '2000-01-01' + end_time) WITH &&,
    daterange(valid_from, valid_to, '[]') WITH &&
  ) WHERE (active)
"""

_CLINIC_CHECKS = {
    "ck_clinic_max_overbookings_nonneg": "max_overbookings_per_day >= 0",
    "ck_clinic_waitlist_offer_ttl_positive": "waitlist_offer_ttl_hours > 0",
}

_TRIGGER_FN = """
CREATE FUNCTION agenda_config_event_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'agenda_config_event es append-only: % no permitido', TG_OP
    USING ERRCODE = 'integrity_constraint_violation';
END;
$$
"""


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Anti-solape de la plantilla semanal (RN-AG-05) — ver excepción en el encabezado.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(_EXCLUDE_SCHEDULE_RULE)

    # 2. Políticas de clínica: ADD COLUMN metadata-only + CHECK NOT VALID → VALIDATE.
    op.add_column(
        "clinic",
        sa.Column(
            "max_overbookings_per_day", sa.Integer(), server_default=sa.text("2"), nullable=False
        ),
    )
    op.add_column(
        "clinic",
        sa.Column(
            "waitlist_offer_ttl_hours", sa.Integer(), server_default=sa.text("4"), nullable=False
        ),
    )
    for nombre, condicion in _CLINIC_CHECKS.items():
        op.execute(f"ALTER TABLE clinic ADD CONSTRAINT {nombre} CHECK ({condicion}) NOT VALID")
    for nombre in _CLINIC_CHECKS:
        op.execute(f"ALTER TABLE clinic VALIDATE CONSTRAINT {nombre}")

    # 3. Bloqueos de agenda (RN-BL-01/03/04).
    BLOCK_REASON.create(bind, checkfirst=False)
    op.create_table(
        "block",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("clinic_id", UUID, nullable=False),
        sa.Column("professional_id", UUID, nullable=True),
        sa.Column("chair_id", UUID, nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", BLOCK_REASON, nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", UUID, nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_by_user_id", UUID, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_block")),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinic.id"], name=op.f("fk_block_clinic_id_clinic")
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "professional_id"],
            ["professional.clinic_id", "professional.id"],
            name=op.f("fk_block_clinic_id_professional_id_professional"),
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "chair_id"],
            ["chair.clinic_id", "chair.id"],
            name=op.f("fk_block_clinic_id_chair_id_chair"),
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "created_by_user_id"],
            ["user.clinic_id", "user.id"],
            name=op.f("fk_block_clinic_id_created_by_user_id_user"),
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "removed_by_user_id"],
            ["user.clinic_id", "user.id"],
            name=op.f("fk_block_clinic_id_removed_by_user_id_user"),
        ),
        sa.CheckConstraint(
            "professional_id IS NOT NULL OR chair_id IS NOT NULL",
            name=op.f("ck_block_has_target"),
        ),
        sa.CheckConstraint("ends_at > starts_at", name=op.f("ck_block_range_order")),
        sa.CheckConstraint("char_length(notes) <= 500", name=op.f("ck_block_notes_length")),
    )
    op.create_index(op.f("ix_block_clinic_id_starts_at"), "block", ["clinic_id", "starts_at"])

    # 4. Auditoría append-only de configuración (US-001 CA-3).
    CONFIG_ENTITY.create(bind, checkfirst=False)
    CONFIG_ACTION.create(bind, checkfirst=False)
    op.create_table(
        "agenda_config_event",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("clinic_id", UUID, nullable=False),
        sa.Column("actor_user_id", UUID, nullable=False),
        sa.Column("entity", CONFIG_ENTITY, nullable=False),
        sa.Column("entity_id", UUID, nullable=False),
        sa.Column("action", CONFIG_ACTION, nullable=False),
        sa.Column(
            "changes",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agenda_config_event")),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinic.id"], name=op.f("fk_agenda_config_event_clinic_id_clinic")
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "actor_user_id"],
            ["user.clinic_id", "user.id"],
            name=op.f("fk_agenda_config_event_clinic_id_actor_user_id_user"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(changes) = 'object'",
            name=op.f("ck_agenda_config_event_changes_is_object"),
        ),
    )
    op.create_index(
        op.f("ix_agenda_config_event_clinic_id_created_at"),
        "agenda_config_event",
        ["clinic_id", "created_at"],
    )
    op.execute(_TRIGGER_FN)
    op.execute(
        "CREATE TRIGGER trg_agenda_config_event_no_mutate BEFORE UPDATE OR DELETE "
        "ON agenda_config_event FOR EACH ROW EXECUTE FUNCTION agenda_config_event_immutable()"
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.execute("DROP TRIGGER IF EXISTS trg_agenda_config_event_no_mutate ON agenda_config_event")
    op.execute("DROP FUNCTION IF EXISTS agenda_config_event_immutable()")
    op.drop_index(
        op.f("ix_agenda_config_event_clinic_id_created_at"), table_name="agenda_config_event"
    )
    op.drop_table("agenda_config_event")
    CONFIG_ACTION.drop(bind, checkfirst=False)
    CONFIG_ENTITY.drop(bind, checkfirst=False)

    op.drop_index(op.f("ix_block_clinic_id_starts_at"), table_name="block")
    op.drop_table("block")
    BLOCK_REASON.drop(bind, checkfirst=False)

    for nombre in _CLINIC_CHECKS:
        # SQL directo: `op.drop_constraint` re-aplicaría la naming convention al nombre.
        op.execute(f"ALTER TABLE clinic DROP CONSTRAINT {nombre}")
    op.drop_column("clinic", "waitlist_offer_ttl_hours")
    op.drop_column("clinic", "max_overbookings_per_day")

    op.execute("ALTER TABLE schedule_rule DROP CONSTRAINT IF EXISTS ex_schedule_rule_no_overlap")
