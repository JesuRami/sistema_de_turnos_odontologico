"""C-12 lista-de-espera: entradas, ofertas, auditoría y envío de ofertas por el motor.

Revision ID: c12_waiting_list
Revises: c11_reminder_timeline

Regla dura 3: una única revisión por change.

Regla dura 11 (tablas con filas: `appointment`, `reminder_job`, `notification_template`,
`whatsapp_inbound`, `whatsapp_outbound_reply`):
- Valores nuevos de enums nativos con `ALTER TYPE … ADD VALUE` en un `autocommit_block` (no se
  pueden usar en la transacción que los crea).
- Columnas nuevas nullable y sin default (metadata-only); `reminder_job.appointment_id DROP NOT
  NULL` es solo metadato.
- FKs y CHECKs nuevos sobre tablas con filas: `NOT VALID` y luego `VALIDATE CONSTRAINT`.
- Índices sobre tablas con filas: `CONCURRENTLY` en un `autocommit_block`, al final.
- Las tablas nuevas nacen vacías: sus índices, FKs y CHECKs se crean con ellas.

`waitlist_event` es append-only (trigger, regla 7) y no guarda PII (regla 13).

Downgrade: elimina tablas, columnas, constraints e índices. Los valores agregados a enums
existentes quedan (PostgreSQL no los quita); antes de volver a la columna `NOT NULL` se eliminan
los jobs de oferta.
"""

import sqlalchemy as sa
from alembic import op
from app.modules.reminders.templates import DEFAULT_TEMPLATES, STEP_WAITLIST_OFFER
from sqlalchemy.dialects import postgresql

revision: str = "c12_waiting_list"
down_revision: str | None = "c11_reminder_timeline"
branch_labels: str | None = None
depends_on: str | None = None

UUID = postgresql.UUID(as_uuid=True)
GEN_UUID = sa.text("gen_random_uuid()")
NOW = sa.text("now()")

ACTIVE_ENTRY = "status IN ('waiting', 'offered')"
OLD_STEP = "step ~ '^(created|t_[0-9]+h)$'"
NEW_STEP = "step ~ '^(created|waitlist_offer|t_[0-9]+h)$'"

_NEW_ENUM_VALUES = (
    ("appointment_origin", "waitlist"),
    ("whatsapp_intent", "accept_offer"),
    ("whatsapp_intent", "decline_offer"),
    ("whatsapp_reply_kind", "offer_accepted"),
    ("whatsapp_reply_kind", "offer_declined"),
    ("whatsapp_reply_kind", "offer_taken"),
    ("whatsapp_reply_kind", "offer_closed"),
    ("whatsapp_reply_kind", "offer_patient_busy"),
)

_OFFER_CHANNEL_INDEX = "uq_reminder_job_offer_channel"
_OFFER_CHANNEL_DEF = (
    "ON reminder_job (waitlist_offer_id, channel) WHERE waitlist_offer_id IS NOT NULL"
)

_TRIGGER_FN = """
CREATE FUNCTION waitlist_event_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'waitlist_event es append-only: % no permitido', TG_OP
    USING ERRCODE = 'integrity_constraint_violation';
END;
$$
"""


def _add_validated(table: str, name: str, ddl: str) -> None:
    """Constraint sobre una tabla con filas: `NOT VALID` y después `VALIDATE` (regla 11)."""
    op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} {ddl} NOT VALID")
    op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")


def _drop_constraint(table: str, name: str) -> None:
    """Por nombre literal: `op.drop_constraint` le volvería a aplicar la convención de nombres."""
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {name}")


def _create_index_concurrently(name: str, definition: str, *, unique: bool = False) -> None:
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
        f"WHERE c.relname = '{name}' AND NOT i.indisvalid) THEN "
        f"DROP INDEX {name}; END IF; END $$"
    )
    kind = "UNIQUE INDEX" if unique else "INDEX"
    op.execute(f"CREATE {kind} CONCURRENTLY IF NOT EXISTS {name} {definition}")


def upgrade() -> None:
    # 1. Valores de enums existentes (fuera de la transacción).
    with op.get_context().autocommit_block():
        for enum_name, value in _NEW_ENUM_VALUES:
            op.execute(f"ALTER TYPE {enum_name} ADD VALUE IF NOT EXISTS '{value}'")

    # 2. Enums nuevos.
    postgresql.ENUM(
        "waiting", "offered", "converted", "expired", "withdrawn", name="waiting_list_status"
    ).create(op.get_bind())
    postgresql.ENUM(
        "pending", "accepted", "declined", "expired", "cancelled", name="waitlist_offer_status"
    ).create(op.get_bind())
    postgresql.ENUM(
        "entry_created",
        "entry_updated",
        "entry_prioritized",
        "entry_unprioritized",
        "entry_withdrawn",
        "entry_expired",
        "entry_converted",
        "offer_created",
        "offer_accepted",
        "offer_declined",
        "offer_expired",
        "offer_cancelled",
        name="waitlist_event_type",
    ).create(op.get_bind())

    entry_status = postgresql.ENUM(name="waiting_list_status", create_type=False)
    offer_status = postgresql.ENUM(name="waitlist_offer_status", create_type=False)
    event_type = postgresql.ENUM(name="waitlist_event_type", create_type=False)
    actor_type = postgresql.ENUM(name="actor_type", create_type=False)

    # 3. Entradas.
    op.create_table(
        "waiting_list_entry",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("clinic_id", UUID, nullable=False),
        sa.Column("patient_id", UUID, nullable=False),
        sa.Column("professional_id", UUID, nullable=True),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("time_from", sa.Time(), nullable=True),
        sa.Column("time_to", sa.Time(), nullable=True),
        sa.Column("weekdays", postgresql.ARRAY(sa.SmallInteger()), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", entry_status, server_default=sa.text("'waiting'"), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("prioritized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("priority_reason", sa.Text(), nullable=True),
        sa.Column(
            "consecutive_expired", sa.SmallInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("closed_reason", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", UUID, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_waiting_list_entry")),
        sa.UniqueConstraint("clinic_id", "id", name=op.f("uq_waiting_list_entry_clinic_id_id")),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinic.id"], name=op.f("fk_waiting_list_entry_clinic_id_clinic")
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "patient_id"],
            ["patient.clinic_id", "patient.id"],
            name="fk_waiting_list_entry_patient",
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "professional_id"],
            ["professional.clinic_id", "professional.id"],
            name="fk_waiting_list_entry_professional",
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "created_by_user_id"],
            ["user.clinic_id", "user.id"],
            name="fk_waiting_list_entry_creator",
        ),
        sa.CheckConstraint("date_to >= date_from", name=op.f("ck_waiting_list_entry_date_range")),
        sa.CheckConstraint(
            "(time_from IS NULL AND time_to IS NULL) "
            "OR (time_from IS NOT NULL AND time_to IS NOT NULL AND time_to > time_from)",
            name=op.f("ck_waiting_list_entry_time_window"),
        ),
        sa.CheckConstraint(
            "weekdays IS NULL OR (cardinality(weekdays) BETWEEN 1 AND 7 "
            "AND weekdays <@ ARRAY[0, 1, 2, 3, 4, 5, 6]::smallint[])",
            name=op.f("ck_waiting_list_entry_weekdays_valid"),
        ),
        sa.CheckConstraint(
            "notes IS NULL OR char_length(notes) <= 200",
            name=op.f("ck_waiting_list_entry_notes_length"),
        ),
        sa.CheckConstraint(
            "consecutive_expired >= 0",
            name=op.f("ck_waiting_list_entry_consecutive_expired_nonneg"),
        ),
        sa.CheckConstraint(
            "source IN ('reception', 'online')", name=op.f("ck_waiting_list_entry_source_valid")
        ),
        sa.CheckConstraint(
            "(prioritized_at IS NULL) = (priority_reason IS NULL) "
            "AND (priority_reason IS NULL OR char_length(priority_reason) <= 200)",
            name=op.f("ck_waiting_list_entry_priority_coherent"),
        ),
        sa.CheckConstraint(
            f"({ACTIVE_ENTRY}) OR closed_reason IS NOT NULL",
            name=op.f("ck_waiting_list_entry_closed_has_reason"),
        ),
    )
    op.create_index(
        "uq_waiting_list_entry_active",
        "waiting_list_entry",
        ["clinic_id", "patient_id", "professional_id"],
        unique=True,
        postgresql_where=sa.text(ACTIVE_ENTRY),
        postgresql_nulls_not_distinct=True,
    )
    op.create_index(
        "ix_waiting_list_entry_queue",
        "waiting_list_entry",
        ["clinic_id", sa.text("prioritized_at NULLS LAST"), "created_at", "id"],
        postgresql_where=sa.text(ACTIVE_ENTRY),
    )
    op.create_index(
        "ix_waiting_list_entry_patient", "waiting_list_entry", ["clinic_id", "patient_id"]
    )

    # 4. Ofertas.
    op.create_table(
        "waitlist_offer",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("clinic_id", UUID, nullable=False),
        sa.Column("entry_id", UUID, nullable=False),
        sa.Column("professional_id", UUID, nullable=False),
        sa.Column("chair_id", UUID, nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", offer_status, server_default=sa.text("'pending'"), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("source_appointment_id", UUID, nullable=True),
        sa.Column("appointment_id", UUID, nullable=True),
        sa.Column("closed_reason", sa.Text(), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", UUID, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_waitlist_offer")),
        sa.UniqueConstraint("clinic_id", "id", name=op.f("uq_waitlist_offer_clinic_id_id")),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinic.id"], name=op.f("fk_waitlist_offer_clinic_id_clinic")
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "entry_id"],
            ["waiting_list_entry.clinic_id", "waiting_list_entry.id"],
            name="fk_waitlist_offer_entry",
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "professional_id"],
            ["professional.clinic_id", "professional.id"],
            name="fk_waitlist_offer_professional",
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "chair_id"],
            ["chair.clinic_id", "chair.id"],
            name="fk_waitlist_offer_chair",
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "source_appointment_id"],
            ["appointment.clinic_id", "appointment.id"],
            name="fk_waitlist_offer_source_appointment",
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "appointment_id"],
            ["appointment.clinic_id", "appointment.id"],
            name="fk_waitlist_offer_appointment",
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "created_by_user_id"],
            ["user.clinic_id", "user.id"],
            name="fk_waitlist_offer_creator",
        ),
        sa.CheckConstraint("ends_at > starts_at", name=op.f("ck_waitlist_offer_range_order")),
        sa.CheckConstraint(
            "expires_at <= starts_at", name=op.f("ck_waitlist_offer_expires_before_start")
        ),
        sa.CheckConstraint("mode IN ('auto', 'manual')", name=op.f("ck_waitlist_offer_mode_valid")),
        sa.CheckConstraint(
            "(status = 'accepted') = (appointment_id IS NOT NULL)",
            name=op.f("ck_waitlist_offer_accepted_has_appointment"),
        ),
    )
    op.create_index(
        "uq_waitlist_offer_pending",
        "waitlist_offer",
        ["entry_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_waitlist_offer_due",
        "waitlist_offer",
        ["expires_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_waitlist_offer_slot", "waitlist_offer", ["clinic_id", "professional_id", "starts_at"]
    )
    op.create_index("ix_waitlist_offer_entry", "waitlist_offer", ["clinic_id", "entry_id"])

    # 5. Auditoría append-only.
    op.create_table(
        "waitlist_event",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("clinic_id", UUID, nullable=False),
        sa.Column("entry_id", UUID, nullable=False),
        sa.Column("offer_id", UUID, nullable=True),
        sa.Column("event", event_type, nullable=False),
        sa.Column("actor_type", actor_type, nullable=False),
        sa.Column("actor_user_id", UUID, nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_waitlist_event")),
        sa.ForeignKeyConstraint(["clinic_id"], ["clinic.id"], name="fk_waitlist_event_clinic"),
        sa.ForeignKeyConstraint(
            ["clinic_id", "entry_id"],
            ["waiting_list_entry.clinic_id", "waiting_list_entry.id"],
            name="fk_waitlist_event_entry",
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "offer_id"],
            ["waitlist_offer.clinic_id", "waitlist_offer.id"],
            name="fk_waitlist_event_offer",
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "actor_user_id"],
            ["user.clinic_id", "user.id"],
            name="fk_waitlist_event_actor",
        ),
        sa.CheckConstraint(
            "actor_type <> 'user' OR actor_user_id IS NOT NULL",
            name=op.f("ck_waitlist_event_actor_user_coherent"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name=op.f("ck_waitlist_event_payload_is_object")
        ),
    )
    op.create_index(
        "ix_waitlist_event_entry", "waitlist_event", ["clinic_id", "entry_id", "created_at"]
    )
    op.create_index(
        "ix_waitlist_event_report", "waitlist_event", ["clinic_id", "event", "created_at"]
    )
    op.create_index("ix_waitlist_event_offer", "waitlist_event", ["offer_id", "created_at"])
    op.execute(_TRIGGER_FN)
    op.execute(
        "CREATE TRIGGER trg_waitlist_event_no_mutate BEFORE UPDATE OR DELETE "
        "ON waitlist_event FOR EACH ROW EXECUTE FUNCTION waitlist_event_immutable()"
    )

    # 6. Turno `waitlist`: ni sobreturno ni token aleatorio.
    _add_validated(
        "appointment",
        "ck_appointment_waitlist_plain",
        "CHECK (origin <> 'waitlist' OR (NOT is_overbooking AND manage_token_hash IS NULL))",
    )

    # 7. `reminder_job` admite un job de oferta.
    op.add_column("reminder_job", sa.Column("waitlist_offer_id", UUID, nullable=True))
    op.alter_column("reminder_job", "appointment_id", nullable=True)
    _add_validated(
        "reminder_job",
        "fk_reminder_job_offer",
        "FOREIGN KEY (clinic_id, waitlist_offer_id) " "REFERENCES waitlist_offer (clinic_id, id)",
    )
    _add_validated(
        "reminder_job",
        "ck_reminder_job_one_target",
        "CHECK (num_nonnulls(appointment_id, waitlist_offer_id) = 1)",
    )
    _add_validated(
        "reminder_job",
        "ck_reminder_job_offer_step",
        "CHECK ((step = 'waitlist_offer') = (waitlist_offer_id IS NOT NULL))",
    )
    for table in ("reminder_job", "notification_template"):
        _drop_constraint(table, f"ck_{table}_step_format")
        _add_validated(table, f"ck_{table}_step_format", f"CHECK ({NEW_STEP})")

    # 7.b Plantillas por defecto de la oferta en cada clínica existente (idempotente: no pisa
    # una plantilla que ya exista).
    for spec in [t for t in DEFAULT_TEMPLATES if t.step == STEP_WAITLIST_OFFER]:
        op.get_bind().execute(
            sa.text(
                "INSERT INTO notification_template "
                "(clinic_id, channel, step, meta_template_name, body_preview) "
                "SELECT id, CAST(:channel AS reminder_channel), :step, :name, :body FROM clinic "
                "ON CONFLICT (clinic_id, channel, step) DO NOTHING"
            ),
            {
                "channel": spec.channel,
                "step": spec.step,
                "name": spec.meta_template_name,
                "body": spec.body_preview,
            },
        )

    # 8. Entrantes y respuestas de WhatsApp que apuntan a una oferta.
    for table, fk in (
        ("whatsapp_inbound", "fk_whatsapp_inbound_offer"),
        ("whatsapp_outbound_reply", "fk_whatsapp_outbound_reply_offer"),
    ):
        op.add_column(table, sa.Column("waitlist_offer_id", UUID, nullable=True))
        _add_validated(
            table,
            fk,
            "FOREIGN KEY (clinic_id, waitlist_offer_id) REFERENCES waitlist_offer (clinic_id, id)",
        )

    # 9. Índice sobre una tabla con filas, sin bloquear escrituras.
    with op.get_context().autocommit_block():
        _create_index_concurrently(_OFFER_CHANNEL_INDEX, _OFFER_CHANNEL_DEF, unique=True)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_OFFER_CHANNEL_INDEX}")
    for table, fk in (
        ("whatsapp_outbound_reply", "fk_whatsapp_outbound_reply_offer"),
        ("whatsapp_inbound", "fk_whatsapp_inbound_offer"),
    ):
        _drop_constraint(table, fk)
        op.drop_column(table, "waitlist_offer_id")
    for table in ("reminder_job", "notification_template"):
        _drop_constraint(table, f"ck_{table}_step_format")
    # Lo que solo existe por C-12 se elimina antes de restaurar las restricciones de C-11.
    op.execute(
        "DELETE FROM delivery_event WHERE reminder_job_id IN "
        "(SELECT id FROM reminder_job WHERE waitlist_offer_id IS NOT NULL)"
    )
    op.execute("DELETE FROM reminder_job WHERE waitlist_offer_id IS NOT NULL")
    op.execute("DELETE FROM notification_template WHERE step = 'waitlist_offer'")
    for table in ("reminder_job", "notification_template"):
        _add_validated(table, f"ck_{table}_step_format", f"CHECK ({OLD_STEP})")
    _drop_constraint("reminder_job", "ck_reminder_job_offer_step")
    _drop_constraint("reminder_job", "ck_reminder_job_one_target")
    _drop_constraint("reminder_job", "fk_reminder_job_offer")
    op.alter_column("reminder_job", "appointment_id", nullable=False)
    op.drop_column("reminder_job", "waitlist_offer_id")
    _drop_constraint("appointment", "ck_appointment_waitlist_plain")

    op.execute("DROP TRIGGER IF EXISTS trg_waitlist_event_no_mutate ON waitlist_event")
    op.execute("DROP FUNCTION IF EXISTS waitlist_event_immutable()")
    op.drop_table("waitlist_event")
    op.drop_table("waitlist_offer")
    op.drop_table("waiting_list_entry")
    for name in ("waitlist_event_type", "waitlist_offer_status", "waiting_list_status"):
        op.execute(f"DROP TYPE IF EXISTS {name}")
