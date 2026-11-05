"""C-09 motor-recordatorios: `notification_template`, `reminder_job`, `delivery_event`, `consent`.

Revision ID: c09_reminder_engine
Revises: c08_manage_token

Regla dura 3: una única revisión por change.

Regla dura 11: las cuatro tablas son nuevas y vacías, así que sus índices, FKs y CHECKs se crean
junto con la tabla, invisibles hasta el commit; no hay filas que validar ni `CONCURRENTLY` que
usar. No se toca ninguna columna de una tabla existente. Las FKs compuestas `(clinic_id, x)`
apuntan a UNIQUEs que ya existen (`appointment`, `patient`, `user`) o que esta revisión crea
(`notification_template`, `reminder_job`).

Datos (idempotentes, `ON CONFLICT DO NOTHING` / `NOT EXISTS`):
- una fila `consent` `whatsapp/opt_in/legacy` por paciente con `whatsapp_opt_in = true`: el
  origen real no se conoce y `legacy` lo dice en vez de inventar `booking`;
- las plantillas por defecto del catálogo (`app.modules.reminders.templates`) para cada clínica.

`delivery_event` y `consent` son append-only: un trigger rechaza `UPDATE`/`DELETE` (regla 7).

Downgrade: elimina las cuatro tablas, sus triggers y los enums (pérdida de datos del motor). El
flag `patient.whatsapp_opt_in` no se toca.
"""

import sqlalchemy as sa
from alembic import op
from app.modules.reminders.templates import DEFAULT_TEMPLATES
from sqlalchemy.dialects import postgresql

revision: str = "c09_reminder_engine"
down_revision: str | None = "c08_manage_token"
branch_labels: str | None = None
depends_on: str | None = None

UUID = postgresql.UUID(as_uuid=True)
GEN_UUID = sa.text("gen_random_uuid()")
NOW = sa.text("now()")
CLOCK = sa.text("clock_timestamp()")

REMINDER_CHANNEL = postgresql.ENUM("whatsapp", "email", name="reminder_channel", create_type=False)
REMINDER_STATUS = postgresql.ENUM(
    "scheduled",
    "sending",
    "sent",
    "delivered",
    "read",
    "failed",
    "skipped",
    "cancelled",
    name="reminder_status",
    create_type=False,
)
CONSENT_STATUS = postgresql.ENUM("opt_in", "opt_out", name="consent_status", create_type=False)
CONSENT_SOURCE = postgresql.ENUM(
    "booking", "whatsapp_reply", "reception", "legacy", name="consent_source", create_type=False
)
DELIVERY_EVENT_TYPE = postgresql.ENUM(
    "sent",
    "attempt_failed",
    "failed",
    "skipped",
    "cancelled",
    "escalated",
    "lease_expired",
    "delivered",
    "read",
    name="delivery_event_type",
    create_type=False,
)
_ENUMS = (REMINDER_CHANNEL, REMINDER_STATUS, CONSENT_STATUS, CONSENT_SOURCE, DELIVERY_EVENT_TYPE)

_STEP_FORMAT = "step ~ '^(created|t_[0-9]+h)$'"

_TRIGGER_FN = """
CREATE FUNCTION {tabla}_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '{tabla} es append-only: % no permitido', TG_OP
    USING ERRCODE = 'integrity_constraint_violation';
END;
$$
"""


def _append_only(tabla: str) -> None:
    op.execute(_TRIGGER_FN.format(tabla=tabla))
    op.execute(
        f"CREATE TRIGGER trg_{tabla}_no_mutate BEFORE UPDATE OR DELETE "
        f"ON {tabla} FOR EACH ROW EXECUTE FUNCTION {tabla}_immutable()"
    )


def upgrade() -> None:
    bind = op.get_bind()
    for tipo in _ENUMS:
        tipo.create(bind, checkfirst=False)

    op.create_table(
        "notification_template",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("clinic_id", UUID, nullable=False),
        sa.Column("channel", REMINDER_CHANNEL, nullable=False),
        sa.Column("step", sa.Text(), nullable=False),
        sa.Column("meta_template_name", sa.Text(), nullable=False),
        sa.Column("locale", sa.Text(), server_default=sa.text("'es_AR'"), nullable=False),
        sa.Column("body_preview", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_template")),
        sa.UniqueConstraint("clinic_id", "id", name=op.f("uq_notification_template_clinic_id_id")),
        sa.UniqueConstraint(
            "clinic_id",
            "channel",
            "step",
            name=op.f("uq_notification_template_clinic_id_channel_step"),
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinic.id"], name=op.f("fk_notification_template_clinic_id_clinic")
        ),
        sa.CheckConstraint(_STEP_FORMAT, name=op.f("ck_notification_template_step_format")),
        sa.CheckConstraint("locale = 'es_AR'", name=op.f("ck_notification_template_locale_es_ar")),
        sa.CheckConstraint(
            "btrim(meta_template_name) <> ''", name=op.f("ck_notification_template_name_not_blank")
        ),
        sa.CheckConstraint(
            "btrim(body_preview) <> ''", name=op.f("ck_notification_template_body_not_blank")
        ),
    )

    op.create_table(
        "reminder_job",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("clinic_id", UUID, nullable=False),
        sa.Column("appointment_id", UUID, nullable=False),
        sa.Column("step", sa.Text(), nullable=False),
        sa.Column("channel", REMINDER_CHANNEL, nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("starts_at_snapshot", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", REMINDER_STATUS, server_default=sa.text("'scheduled'"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("template_id", UUID, nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.Text(), nullable=True),
        sa.Column("cost_micros", sa.BigInteger(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reminder_job")),
        sa.UniqueConstraint("clinic_id", "id", name=op.f("uq_reminder_job_clinic_id_id")),
        sa.UniqueConstraint(
            "appointment_id",
            "step",
            "channel",
            name=op.f("uq_reminder_job_appointment_id_step_channel"),
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinic.id"], name=op.f("fk_reminder_job_clinic_id_clinic")
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "appointment_id"],
            ["appointment.clinic_id", "appointment.id"],
            name=op.f("fk_reminder_job_clinic_id_appointment_id_appointment"),
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "template_id"],
            ["notification_template.clinic_id", "notification_template.id"],
            name=op.f("fk_reminder_job_clinic_id_template_id_notification_template"),
        ),
        sa.CheckConstraint(_STEP_FORMAT, name=op.f("ck_reminder_job_step_format")),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_reminder_job_attempts_nonneg")),
        sa.CheckConstraint(
            "cost_micros IS NULL OR cost_micros >= 0", name=op.f("ck_reminder_job_cost_nonneg")
        ),
        sa.CheckConstraint(
            "status <> 'sending' OR claimed_at IS NOT NULL",
            name=op.f("ck_reminder_job_sending_has_claim"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('sent', 'delivered', 'read') OR sent_at IS NOT NULL",
            name=op.f("ck_reminder_job_sent_has_sent_at"),
        ),
        sa.CheckConstraint(
            "char_length(last_error) <= 64", name=op.f("ck_reminder_job_last_error_code")
        ),
    )
    op.create_index(
        "ix_reminder_job_due",
        "reminder_job",
        ["available_at"],
        postgresql_where=sa.text("status = 'scheduled'"),
    )
    op.create_index(
        "ix_reminder_job_claimed",
        "reminder_job",
        ["claimed_at"],
        postgresql_where=sa.text("status = 'sending'"),
    )
    op.create_index(
        "ix_reminder_job_clinic_step_sent", "reminder_job", ["clinic_id", "step", "sent_at"]
    )

    op.create_table(
        "delivery_event",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("clinic_id", UUID, nullable=False),
        sa.Column("reminder_job_id", UUID, nullable=False),
        sa.Column("event_type", DELIVERY_EVENT_TYPE, nullable=False),
        sa.Column("provider_event_id", sa.Text(), nullable=True),
        sa.Column(
            "payload", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=CLOCK, nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=CLOCK, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_delivery_event")),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinic.id"], name=op.f("fk_delivery_event_clinic_id_clinic")
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "reminder_job_id"],
            ["reminder_job.clinic_id", "reminder_job.id"],
            name=op.f("fk_delivery_event_clinic_id_reminder_job_id_reminder_job"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name=op.f("ck_delivery_event_payload_is_object")
        ),
    )
    op.create_index(
        op.f("ix_delivery_event_reminder_job_id_occurred_at"),
        "delivery_event",
        ["reminder_job_id", "occurred_at"],
    )
    op.create_index(
        "uq_delivery_event_job_provider_event",
        "delivery_event",
        ["reminder_job_id", "provider_event_id"],
        unique=True,
        postgresql_where=sa.text("provider_event_id IS NOT NULL"),
    )
    _append_only("delivery_event")

    op.create_table(
        "consent",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("clinic_id", UUID, nullable=False),
        sa.Column("patient_id", UUID, nullable=False),
        sa.Column("channel", REMINDER_CHANNEL, nullable=False),
        sa.Column("status", CONSENT_STATUS, nullable=False),
        sa.Column("source", CONSENT_SOURCE, nullable=False),
        sa.Column("changed_by_user_id", UUID, nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=CLOCK, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consent")),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinic.id"], name=op.f("fk_consent_clinic_id_clinic")
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "patient_id"],
            ["patient.clinic_id", "patient.id"],
            name=op.f("fk_consent_clinic_id_patient_id_patient"),
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "changed_by_user_id"],
            ["user.clinic_id", "user.id"],
            name=op.f("fk_consent_clinic_id_changed_by_user_id_user"),
        ),
        sa.CheckConstraint(
            "source <> 'reception' OR changed_by_user_id IS NOT NULL",
            name=op.f("ck_consent_reception_has_user"),
        ),
    )
    op.create_index(
        "ix_consent_patient_channel_changed",
        "consent",
        ["patient_id", "channel", sa.text("changed_at DESC")],
    )
    _append_only("consent")

    _backfill(bind)


def _backfill(bind: sa.engine.Connection) -> None:
    """Consentimiento previo y plantillas por defecto; idempotente."""
    bind.execute(
        sa.text(
            "INSERT INTO consent (clinic_id, patient_id, channel, status, source) "
            "SELECT p.clinic_id, p.id, 'whatsapp', 'opt_in', 'legacy' FROM patient p "
            "WHERE p.whatsapp_opt_in AND NOT EXISTS ("
            "  SELECT 1 FROM consent c WHERE c.patient_id = p.id AND c.channel = 'whatsapp')"
        )
    )
    for spec in DEFAULT_TEMPLATES:
        bind.execute(
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


def downgrade() -> None:
    bind = op.get_bind()
    for tabla in ("consent", "delivery_event"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{tabla}_no_mutate ON {tabla}")
        op.execute(f"DROP FUNCTION IF EXISTS {tabla}_immutable()")
    op.drop_table("consent")
    op.drop_table("delivery_event")
    op.drop_table("reminder_job")
    op.drop_table("notification_template")
    for tipo in reversed(_ENUMS):
        tipo.drop(bind, checkfirst=False)
