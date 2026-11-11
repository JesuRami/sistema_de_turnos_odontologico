"""C-15 historia-clinica-odontograma: ficha, anamnesis, odontograma, evoluciones, adjuntos,
presupuestos y bitácora de accesos.

Revision ID: c15_clinical_record
Revises: c14_hardening_pilot

Regla dura 3: una única revisión por change. Solo `CREATE` de objetos nuevos: ninguna tabla
existente se altera (DD-02). Las tablas nacen vacías, así que sus índices, FKs y CHECKs se crean
con ellas (sin `CONCURRENTLY` ni `NOT VALID`: no hay filas que validar ni escrituras que
bloquear; la regla 11 aplica a tablas con filas).

- `clinic_id NOT NULL` en todas y FKs compuestas `(clinic_id, id)` (regla 4).
- Append-only (D1, Ley 26.529): trigger `BEFORE UPDATE OR DELETE` en todas salvo el catálogo
  `odontogram_condition` (operativo: `active` se desactiva, nunca se borra). Las tablas se suman a
  `APPEND_ONLY_TABLES` y se re-ejecuta `grant_statements()` para que `app_writer` quede sin
  `UPDATE` (C-14, D7).
- Catálogo inicial (provisional, Decisión 8) sembrado para cada clínica existente.

Downgrade: elimina tablas, trigger y enums nuevos. **Destruye los datos clínicos cargados**
(design §Migration Plan: exigir dump previo; no recomendado con datos reales).
"""

from typing import Any

import sqlalchemy as sa
from alembic import op
from app.modules.clinical.catalog import INITIAL_CONDITIONS, SEED_CONDITIONS_SQL
from app.ops.db_privileges import grant_statements
from sqlalchemy.dialects import postgresql

revision: str = "c15_clinical_record"
down_revision: str | None = "c14_hardening_pilot"
branch_labels: str | None = None
depends_on: str | None = None

UUID = postgresql.UUID(as_uuid=True)
GEN_UUID = sa.text("gen_random_uuid()")
NOW = sa.text("now()")
CLOCK = sa.text("clock_timestamp()")

FDI = (
    "({c} / 10 BETWEEN 1 AND 4 AND {c} % 10 BETWEEN 1 AND 8) "
    "OR ({c} / 10 BETWEEN 5 AND 8 AND {c} % 10 BETWEEN 1 AND 5)"
)
PAYLOAD_SAFE = (
    "jsonb_typeof(payload) = 'object' AND NOT jsonb_path_exists(payload, "
    '\'$.* ? (@.type() == "object" || @.type() == "array" '
    '|| (@.type() == "string" && !(@ like_regex "^[0-9a-z_-]{1,64}$")))\')'
)

_ENUMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("tooth_surface", ("M", "D", "O", "V", "L", "W")),
    ("evolution_kind", ("entry", "correction")),
    ("attachment_kind", ("xray", "photo", "document", "other")),
    ("plan_decision", ("accepted", "rejected")),
    (
        "clinical_action",
        (
            "record_open",
            "record_read",
            "anamnesis_write",
            "anamnesis_read",
            "odontogram_write",
            "odontogram_read",
            "odontogram_history_read",
            "evolution_write",
            "evolution_correct",
            "evolution_read",
            "attachment_upload",
            "attachment_list",
            "attachment_download",
            "attachment_remove",
            "plan_write",
            "plan_version_write",
            "plan_decision",
            "plan_list",
            "plan_read",
            "plan_pdf_export",
            "access_log_read",
        ),
    ),
)

# En orden de creación; el downgrade las elimina al revés.
APPEND_ONLY = (
    "clinical_record",
    "anamnesis_version",
    "clinical_evolution",
    "odontogram_event",
    "clinical_attachment",
    "clinical_attachment_removal",
    "treatment_plan",
    "treatment_plan_version",
    "treatment_plan_item",
    "treatment_plan_decision",
    "clinical_access_event",
)

_TRIGGER_FN = """
CREATE FUNCTION clinical_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% es append-only: % no permitido', TG_TABLE_NAME, TG_OP
    USING ERRCODE = 'integrity_constraint_violation';
END;
$$
"""


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(name=name, create_type=False)


def _pk(table: str) -> sa.PrimaryKeyConstraint:
    return sa.PrimaryKeyConstraint("id", name=f"pk_{table}")


def _clinic_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["clinic_id"], ["clinic.id"], name=f"fk_{table}_clinic")


def _fk(table: str, suffix: str, column: str, target: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["clinic_id", column], [f"{target}.clinic_id", f"{target}.id"], name=f"fk_{table}_{suffix}"
    )


def _uq_clinic_id(table: str) -> sa.UniqueConstraint:
    return sa.UniqueConstraint("clinic_id", "id", name=f"uq_{table}_clinic_id_id")


def _base(table: str) -> list[sa.Column[Any]]:
    return [
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("clinic_id", UUID, nullable=False),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in _ENUMS:
        postgresql.ENUM(*values, name=name).create(bind)

    op.create_table(
        "clinical_record",
        *_base("clinical_record"),
        sa.Column("patient_id", UUID, nullable=False),
        sa.Column("created_by_user_id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        _pk("clinical_record"),
        _uq_clinic_id("clinical_record"),
        sa.UniqueConstraint(
            "clinic_id", "patient_id", name="uq_clinical_record_clinic_id_patient_id"
        ),
        _clinic_fk("clinical_record"),
        _fk("clinical_record", "patient", "patient_id", "patient"),
        _fk("clinical_record", "creator", "created_by_user_id", "user"),
    )

    op.create_table(
        "anamnesis_version",
        *_base("anamnesis_version"),
        sa.Column("record_id", UUID, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("answers", postgresql.JSONB(), nullable=False),
        sa.Column("created_by_user_id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        _pk("anamnesis_version"),
        _uq_clinic_id("anamnesis_version"),
        sa.UniqueConstraint("record_id", "version", name="uq_anamnesis_version_record_id_version"),
        _clinic_fk("anamnesis_version"),
        _fk("anamnesis_version", "record", "record_id", "clinical_record"),
        _fk("anamnesis_version", "creator", "created_by_user_id", "user"),
        sa.CheckConstraint("version >= 1", name="ck_anamnesis_version_version_positive"),
        sa.CheckConstraint(
            "jsonb_typeof(answers) = 'object'", name="ck_anamnesis_version_answers_is_object"
        ),
    )

    op.create_table(
        "odontogram_condition",
        *_base("odontogram_condition"),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        _pk("odontogram_condition"),
        _uq_clinic_id("odontogram_condition"),
        sa.UniqueConstraint("clinic_id", "code", name="uq_odontogram_condition_clinic_id_code"),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinic.id"], name="fk_odontogram_condition_clinic_id_clinic"
        ),
        sa.CheckConstraint(
            "scope IN ('surface', 'tooth')", name="ck_odontogram_condition_scope_valid"
        ),
        sa.CheckConstraint(
            "code ~ '^[a-z][a-z0-9_]{1,39}$'", name="ck_odontogram_condition_code_format"
        ),
        sa.CheckConstraint(
            "char_length(label) BETWEEN 1 AND 80", name="ck_odontogram_condition_label_length"
        ),
    )

    op.create_table(
        "clinical_evolution",
        *_base("clinical_evolution"),
        sa.Column("record_id", UUID, nullable=False),
        sa.Column("appointment_id", UUID, nullable=True),
        sa.Column("professional_id", UUID, nullable=False),
        sa.Column("created_by_user_id", UUID, nullable=False),
        sa.Column("kind", _enum("evolution_kind"), nullable=False),
        sa.Column("corrects_evolution_id", UUID, nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_sha256", sa.CHAR(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        _pk("clinical_evolution"),
        _uq_clinic_id("clinical_evolution"),
        _clinic_fk("clinical_evolution"),
        _fk("clinical_evolution", "record", "record_id", "clinical_record"),
        _fk("clinical_evolution", "appointment", "appointment_id", "appointment"),
        _fk("clinical_evolution", "professional", "professional_id", "professional"),
        _fk("clinical_evolution", "creator", "created_by_user_id", "user"),
        _fk("clinical_evolution", "corrects", "corrects_evolution_id", "clinical_evolution"),
        sa.CheckConstraint(
            "(kind = 'correction') = (corrects_evolution_id IS NOT NULL) "
            "AND (kind = 'correction') = (reason IS NOT NULL)",
            name="ck_clinical_evolution_correction_coherent",
        ),
        sa.CheckConstraint(
            "char_length(body) BETWEEN 1 AND 4000", name="ck_clinical_evolution_body_length"
        ),
        sa.CheckConstraint(
            "reason IS NULL OR char_length(reason) BETWEEN 10 AND 300",
            name="ck_clinical_evolution_reason_length",
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'", name="ck_clinical_evolution_sha256_hex"
        ),
        sa.CheckConstraint(
            "corrects_evolution_id <> id", name="ck_clinical_evolution_not_self_correction"
        ),
    )
    op.create_index(
        "ix_clinical_evolution_record_signed",
        "clinical_evolution",
        ["record_id", sa.text("signed_at DESC"), sa.text("id DESC")],
    )
    op.create_index(
        "ix_clinical_evolution_record_id_appointment_id",
        "clinical_evolution",
        ["record_id", "appointment_id"],
    )
    op.create_index(
        "ix_clinical_evolution_corrects_evolution_id",
        "clinical_evolution",
        ["corrects_evolution_id"],
    )

    op.create_table(
        "odontogram_event",
        *_base("odontogram_event"),
        sa.Column("record_id", UUID, nullable=False),
        sa.Column("tooth", sa.SmallInteger(), nullable=False),
        sa.Column("surface", _enum("tooth_surface"), nullable=False),
        sa.Column("condition_id", UUID, nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("evolution_id", UUID, nullable=True),
        sa.Column("professional_id", UUID, nullable=False),
        sa.Column("created_by_user_id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=CLOCK, nullable=False),
        _pk("odontogram_event"),
        _uq_clinic_id("odontogram_event"),
        _clinic_fk("odontogram_event"),
        _fk("odontogram_event", "record", "record_id", "clinical_record"),
        _fk("odontogram_event", "condition", "condition_id", "odontogram_condition"),
        _fk("odontogram_event", "evolution", "evolution_id", "clinical_evolution"),
        _fk("odontogram_event", "professional", "professional_id", "professional"),
        _fk("odontogram_event", "creator", "created_by_user_id", "user"),
        sa.CheckConstraint(FDI.format(c="tooth"), name="ck_odontogram_event_fdi_tooth"),
        sa.CheckConstraint(
            "note IS NULL OR char_length(note) <= 500", name="ck_odontogram_event_note_length"
        ),
    )
    op.create_index(
        "ix_odontogram_event_projection",
        "odontogram_event",
        ["record_id", "tooth", "surface", sa.text("created_at DESC"), sa.text("id DESC")],
    )

    op.create_table(
        "clinical_attachment",
        *_base("clinical_attachment"),
        sa.Column("record_id", UUID, nullable=False),
        sa.Column("evolution_id", UUID, nullable=True),
        sa.Column("kind", _enum("attachment_kind"), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.CHAR(64), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("created_by_user_id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=CLOCK, nullable=False),
        _pk("clinical_attachment"),
        _uq_clinic_id("clinical_attachment"),
        sa.UniqueConstraint("storage_key", name="uq_clinical_attachment_storage_key"),
        _clinic_fk("clinical_attachment"),
        _fk("clinical_attachment", "record", "record_id", "clinical_record"),
        _fk("clinical_attachment", "evolution", "evolution_id", "clinical_evolution"),
        _fk("clinical_attachment", "creator", "created_by_user_id", "user"),
        sa.CheckConstraint(
            "size_bytes BETWEEN 1 AND 10485760", name="ck_clinical_attachment_size_bytes_range"
        ),
        sa.CheckConstraint(
            "content_type IN ('image/jpeg', 'image/png', 'application/pdf')",
            name="ck_clinical_attachment_content_type_allowed",
        ),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_clinical_attachment_sha256_hex"),
        sa.CheckConstraint(
            "char_length(display_name) BETWEEN 1 AND 255",
            name="ck_clinical_attachment_display_name_length",
        ),
    )
    op.create_index(
        "ix_clinical_attachment_record_created",
        "clinical_attachment",
        ["record_id", sa.text("created_at DESC"), sa.text("id DESC")],
    )

    op.create_table(
        "clinical_attachment_removal",
        *_base("clinical_attachment_removal"),
        sa.Column("attachment_id", UUID, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("removed_by_user_id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        _pk("clinical_attachment_removal"),
        sa.UniqueConstraint("attachment_id", name="uq_clinical_attachment_removal_attachment_id"),
        _clinic_fk("clinical_attachment_removal"),
        _fk("clinical_attachment_removal", "attachment", "attachment_id", "clinical_attachment"),
        _fk("clinical_attachment_removal", "actor", "removed_by_user_id", "user"),
        sa.CheckConstraint(
            "char_length(reason) BETWEEN 10 AND 300",
            name="ck_clinical_attachment_removal_reason_length",
        ),
    )

    op.create_table(
        "treatment_plan",
        *_base("treatment_plan"),
        sa.Column("record_id", UUID, nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("created_by_user_id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=CLOCK, nullable=False),
        _pk("treatment_plan"),
        _uq_clinic_id("treatment_plan"),
        _clinic_fk("treatment_plan"),
        _fk("treatment_plan", "record", "record_id", "clinical_record"),
        _fk("treatment_plan", "creator", "created_by_user_id", "user"),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 3 AND 120", name="ck_treatment_plan_title_length"
        ),
    )
    op.create_index(
        "ix_treatment_plan_record_created",
        "treatment_plan",
        ["record_id", sa.text("created_at DESC"), sa.text("id DESC")],
    )

    op.create_table(
        "treatment_plan_version",
        *_base("treatment_plan_version"),
        sa.Column("plan_id", UUID, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        _pk("treatment_plan_version"),
        _uq_clinic_id("treatment_plan_version"),
        sa.UniqueConstraint("plan_id", "version", name="uq_treatment_plan_version_plan_id_version"),
        _clinic_fk("treatment_plan_version"),
        _fk("treatment_plan_version", "plan", "plan_id", "treatment_plan"),
        _fk("treatment_plan_version", "creator", "created_by_user_id", "user"),
        sa.CheckConstraint("version >= 1", name="ck_treatment_plan_version_version_positive"),
    )

    op.create_table(
        "treatment_plan_item",
        *_base("treatment_plan_item"),
        sa.Column("version_id", UUID, nullable=False),
        sa.Column("phase", sa.SmallInteger(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price_cents", sa.BigInteger(), nullable=False),
        sa.Column("tooth", sa.SmallInteger(), nullable=True),
        sa.Column("surface", _enum("tooth_surface"), nullable=True),
        _pk("treatment_plan_item"),
        sa.UniqueConstraint(
            "version_id", "position", name="uq_treatment_plan_item_version_id_position"
        ),
        _clinic_fk("treatment_plan_item"),
        _fk("treatment_plan_item", "version", "version_id", "treatment_plan_version"),
        sa.CheckConstraint("phase BETWEEN 1 AND 10", name="ck_treatment_plan_item_phase_range"),
        sa.CheckConstraint("position >= 1", name="ck_treatment_plan_item_position_positive"),
        sa.CheckConstraint("quantity >= 1", name="ck_treatment_plan_item_quantity_positive"),
        sa.CheckConstraint(
            "unit_price_cents >= 0", name="ck_treatment_plan_item_unit_price_nonneg"
        ),
        sa.CheckConstraint(
            "char_length(description) BETWEEN 3 AND 200",
            name="ck_treatment_plan_item_description_length",
        ),
        sa.CheckConstraint(
            f"tooth IS NULL OR ({FDI.format(c='tooth')})", name="ck_treatment_plan_item_fdi_tooth"
        ),
        sa.CheckConstraint(
            "surface IS NULL OR tooth IS NOT NULL",
            name="ck_treatment_plan_item_surface_needs_tooth",
        ),
    )

    op.create_table(
        "treatment_plan_decision",
        *_base("treatment_plan_decision"),
        sa.Column("version_id", UUID, nullable=False),
        sa.Column("decision", _enum("plan_decision"), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("decided_by_user_id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        _pk("treatment_plan_decision"),
        sa.UniqueConstraint("version_id", name="uq_treatment_plan_decision_version_id"),
        _clinic_fk("treatment_plan_decision"),
        _fk("treatment_plan_decision", "version", "version_id", "treatment_plan_version"),
        _fk("treatment_plan_decision", "actor", "decided_by_user_id", "user"),
        sa.CheckConstraint(
            "note IS NULL OR char_length(note) <= 300",
            name="ck_treatment_plan_decision_note_length",
        ),
    )

    op.create_table(
        "clinical_access_event",
        *_base("clinical_access_event"),
        sa.Column("record_id", UUID, nullable=False),
        sa.Column("actor_user_id", UUID, nullable=False),
        sa.Column("action", _enum("clinical_action"), nullable=False),
        sa.Column("object_type", sa.Text(), nullable=True),
        sa.Column("object_id", UUID, nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=CLOCK, nullable=False),
        _pk("clinical_access_event"),
        _clinic_fk("clinical_access_event"),
        _fk("clinical_access_event", "record", "record_id", "clinical_record"),
        _fk("clinical_access_event", "actor", "actor_user_id", "user"),
        sa.CheckConstraint(PAYLOAD_SAFE, name="ck_clinical_access_event_payload_safe"),
        sa.CheckConstraint(
            "object_type IS NULL OR object_type ~ '^[a-z_]{1,40}$'",
            name="ck_clinical_access_event_object_type_format",
        ),
    )
    op.create_index(
        "ix_clinical_access_event_record_created",
        "clinical_access_event",
        ["record_id", sa.text("created_at DESC"), sa.text("id DESC")],
    )

    op.execute(_TRIGGER_FN)
    for table in APPEND_ONLY:
        op.execute(
            f"CREATE TRIGGER trg_{table}_no_mutate BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION clinical_append_only()"
        )

    # Catálogo inicial (provisional) para cada clínica existente; idempotente.
    for spec in INITIAL_CONDITIONS:
        bind.execute(
            sa.text(SEED_CONDITIONS_SQL),
            {
                "clinic_id": None,
                "code": spec.code,
                "label": spec.label,
                "category": spec.category,
                "scope": spec.scope,
            },
        )

    # Al final: `app_writer` queda sin UPDATE en las tablas append-only nuevas.
    for sentencia in grant_statements():
        op.execute(sentencia)


def downgrade() -> None:
    for table in reversed(APPEND_ONLY):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_mutate ON {table}")
    op.execute("DROP FUNCTION IF EXISTS clinical_append_only()")
    for table in (
        "clinical_access_event",
        "treatment_plan_decision",
        "treatment_plan_item",
        "treatment_plan_version",
        "treatment_plan",
        "clinical_attachment_removal",
        "clinical_attachment",
        "odontogram_event",
        "clinical_evolution",
        "odontogram_condition",
        "anamnesis_version",
        "clinical_record",
    ):
        op.drop_table(table)
    for name, _ in reversed(_ENUMS):
        op.execute(f"DROP TYPE IF EXISTS {name}")
