"""Modelo core C-02: clinic, professional, chair, schedule_rule, patient, user.

Revision ID: c02_core_models
Revises: c01_base

Una única revisión por change (regla dura 3). Excepción acotada a la regla 11
(aprobada 2026-11-02, design.md decisión abierta 1): los índices y constraints
se crean con DDL transaccional normal porque pertenecen a tablas creadas en
esta misma revisión (vacías e invisibles hasta el commit); CONCURRENTLY /
NOT VALID -> VALIDATE aplica desde el primer ALTER sobre estas tablas (C-04+).
`pg_trgm` se crea con IF NOT EXISTS y NO se dropea en downgrade (puede ser
usada por otros objetos).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c02_core_models"
down_revision: str | None = "c01_base"
branch_labels: str | None = None
depends_on: str | None = None

UUID = postgresql.UUID(as_uuid=True)
GEN_UUID = sa.text("gen_random_uuid()")
NOW = sa.text("now()")
# Snapshot congelado del default (las migraciones no importan código de la app).
DEFAULT_REMINDER_STEPS = (
    "'["
    '{"offset_h": 72, "channel": "whatsapp"}, '
    '{"offset_h": 24, "channel": "whatsapp"}, '
    '{"offset_h": 3, "channel": "whatsapp"}'
    "]'::jsonb"
)


USER_ROLE = postgresql.ENUM("admin", "recepcion", "odontologo", name="user_role", create_type=False)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    USER_ROLE.create(op.get_bind(), checkfirst=False)

    op.create_table(
        "clinic",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column(
            "timezone",
            sa.Text(),
            server_default=sa.text("'America/Argentina/Buenos_Aires'"),
            nullable=False,
        ),
        sa.Column("booking_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "cancellation_window_hours", sa.Integer(), server_default=sa.text("24"), nullable=False
        ),
        sa.Column(
            "reminder_steps",
            postgresql.JSONB(),
            server_default=sa.text(DEFAULT_REMINDER_STEPS),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clinic")),
        sa.UniqueConstraint("slug", name=op.f("uq_clinic_slug")),
        sa.CheckConstraint(
            "cancellation_window_hours >= 0", name=op.f("ck_clinic_cancellation_window_nonneg")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(reminder_steps) = 'array'", name=op.f("ck_clinic_reminder_steps_array")
        ),
    )

    op.create_table(
        "professional",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("clinic_id", UUID, nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("color", sa.Text(), nullable=True),
        sa.Column(
            "default_duration_min", sa.Integer(), server_default=sa.text("30"), nullable=False
        ),
        sa.Column("buffer_min", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("booking_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_professional")),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinic.id"], name=op.f("fk_professional_clinic_id_clinic")
        ),
        sa.UniqueConstraint("clinic_id", "id", name=op.f("uq_professional_clinic_id_id")),
        sa.CheckConstraint(
            "default_duration_min > 0", name=op.f("ck_professional_default_duration_positive")
        ),
        sa.CheckConstraint("buffer_min >= 0", name=op.f("ck_professional_buffer_nonneg")),
    )
    op.create_index(
        op.f("ix_professional_clinic_id_active"), "professional", ["clinic_id", "active"]
    )

    op.create_table(
        "chair",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("clinic_id", UUID, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chair")),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinic.id"], name=op.f("fk_chair_clinic_id_clinic")
        ),
        sa.UniqueConstraint("clinic_id", "id", name=op.f("uq_chair_clinic_id_id")),
    )
    op.create_index(op.f("ix_chair_clinic_id_active"), "chair", ["clinic_id", "active"])

    op.create_table(
        "schedule_rule",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("clinic_id", UUID, nullable=False),
        sa.Column("professional_id", UUID, nullable=False),
        sa.Column("chair_id", UUID, nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("slot_duration_min", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.Date(), server_default=sa.func.current_date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_schedule_rule")),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinic.id"], name=op.f("fk_schedule_rule_clinic_id_clinic")
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "professional_id"],
            ["professional.clinic_id", "professional.id"],
            name=op.f("fk_schedule_rule_clinic_id_professional_id_professional"),
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "chair_id"],
            ["chair.clinic_id", "chair.id"],
            name=op.f("fk_schedule_rule_clinic_id_chair_id_chair"),
        ),
        sa.CheckConstraint("weekday BETWEEN 0 AND 6", name=op.f("ck_schedule_rule_weekday_range")),
        sa.CheckConstraint("start_time < end_time", name=op.f("ck_schedule_rule_time_order")),
        sa.CheckConstraint("slot_duration_min > 0", name=op.f("ck_schedule_rule_slot_positive")),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_from <= valid_to",
            name=op.f("ck_schedule_rule_validity_order"),
        ),
    )
    op.create_index(
        op.f("ix_schedule_rule_professional_id_chair_id_weekday"),
        "schedule_rule",
        ["professional_id", "chair_id", "weekday"],
    )

    op.create_table(
        "patient",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("clinic_id", UUID, nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("phone_e164", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("dni", sa.Text(), nullable=True),
        sa.Column("whatsapp_opt_in", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("privacy_consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("privacy_consent_version", sa.Text(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_patient")),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinic.id"], name=op.f("fk_patient_clinic_id_clinic")
        ),
        sa.CheckConstraint("btrim(full_name) <> ''", name=op.f("ck_patient_full_name_not_blank")),
        sa.CheckConstraint(
            "phone_e164 IS NOT NULL OR email IS NOT NULL",
            name=op.f("ck_patient_contact_required"),
        ),
        sa.CheckConstraint(
            "phone_e164 IS NULL OR phone_e164 ~ '^\\+[1-9][0-9]{7,14}$'",
            name=op.f("ck_patient_phone_e164_format"),
        ),
        sa.CheckConstraint(
            "privacy_consent_version IS NULL OR privacy_consent_at IS NOT NULL",
            name=op.f("ck_patient_consent_coherent"),
        ),
    )
    op.create_index(op.f("ix_patient_clinic_id_phone_e164"), "patient", ["clinic_id", "phone_e164"])
    op.create_index(
        op.f("ix_patient_full_name_trgm"),
        "patient",
        ["full_name"],
        postgresql_using="gin",
        postgresql_ops={"full_name": "gin_trgm_ops"},
    )

    op.create_table(
        "user",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("clinic_id", UUID, nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", USER_ROLE, nullable=False),
        sa.Column("professional_id", UUID, nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "must_change_password", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user")),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinic.id"], name=op.f("fk_user_clinic_id_clinic")
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "professional_id"],
            ["professional.clinic_id", "professional.id"],
            name=op.f("fk_user_clinic_id_professional_id_professional"),
        ),
        sa.UniqueConstraint("clinic_id", "email", name=op.f("uq_user_clinic_id_email")),
        sa.CheckConstraint("email = lower(email)", name=op.f("ck_user_email_lowercase")),
        sa.CheckConstraint(
            "role <> 'odontologo' OR professional_id IS NOT NULL",
            name=op.f("ck_user_odontologo_requires_professional"),
        ),
    )


def downgrade() -> None:
    op.drop_table("user")
    USER_ROLE.drop(op.get_bind(), checkfirst=False)
    op.drop_table("patient")
    op.drop_table("schedule_rule")
    op.drop_table("chair")
    op.drop_table("professional")
    op.drop_table("clinic")
