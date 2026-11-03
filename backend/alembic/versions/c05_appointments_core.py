"""C-05 appointments-core: `appointment` (2 EXCLUDE + CHECKs) y `appointment_event` append-only.

Revision ID: c05_appointments_core
Revises: c04_agenda_config

Regla dura 3: una única revisión por change. Los EXCLUDE van por DDL (D2).

Regla dura 11:
- `patient`: la FK compuesta `(clinic_id, patient_id)` exige un UNIQUE sobre
  `patient (id, clinic_id)` (orden: `id` primero para no competir con los índices
  por clínica; la FK solo exige el mismo conjunto de columnas), tabla con datos. Se construye con
  `CREATE UNIQUE INDEX CONCURRENTLY` (fuera de transacción, sin bloquear
  escrituras) y se promueve a constraint con `ADD CONSTRAINT … USING INDEX`
  (lock breve, sin re-escaneo). Si una corrida previa dejó el índice inválido,
  se elimina y se reconstruye.
- `appointment` y `appointment_event` son tablas nuevas y vacías: sus índices,
  FKs, CHECKs y EXCLUDE se crean junto con la tabla, invisibles hasta el commit.
  No hace falta `NOT VALID` (no hay filas que validar) ni excepción a la regla.

Rango ocupado: `tstzrange(starts_at, occupied_until, '[)')` (D1). Vigencia del
EXCLUDE: `status IN ('pending','confirmed','present') AND NOT is_overbooking`
(D2/D3): `absent`, `no_show` y `cancelled` liberan el hueco; el sobreturno queda
fuera y lo controla el servicio bajo lock.

Downgrade: elimina turnos y eventos (pérdida de datos; ver README). No elimina
`btree_gist`.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c05_appointments_core"
down_revision: str | None = "c04_agenda_config"
branch_labels: str | None = None
depends_on: str | None = None

UUID = postgresql.UUID(as_uuid=True)
GEN_UUID = sa.text("gen_random_uuid()")
NOW = sa.text("now()")

APPOINTMENT_STATUS = postgresql.ENUM(
    "pending",
    "confirmed",
    "present",
    "absent",
    "no_show",
    "cancelled",
    name="appointment_status",
    create_type=False,
)
APPOINTMENT_ORIGIN = postgresql.ENUM(
    "reception", "online", name="appointment_origin", create_type=False
)
CANCELLATION_REASON = postgresql.ENUM(
    "paciente",
    "profesional",
    "clinica",
    "bloqueo",
    "otro",
    name="cancellation_reason",
    create_type=False,
)
APPOINTMENT_EVENT_TYPE = postgresql.ENUM(
    "created",
    "overbooking_created",
    "confirmed",
    "rescheduled",
    "cancelled",
    "present",
    "absent",
    "no_show",
    "updated",
    name="appointment_event_type",
    create_type=False,
)
ACTOR_TYPE = postgresql.ENUM(
    "user", "patient_token", "system", name="actor_type", create_type=False
)
_ENUMS = (APPOINTMENT_STATUS, APPOINTMENT_ORIGIN, CANCELLATION_REASON, APPOINTMENT_EVENT_TYPE)

_VIGENTE = "status IN ('pending', 'confirmed', 'present') AND NOT is_overbooking"
_EXCLUDES = {
    "ex_appointment_professional_no_overlap": "professional_id",
    "ex_appointment_chair_no_overlap": "chair_id",
}

_PATIENT_UQ = "uq_patient_id_clinic_id"

_TRIGGER_FN = """
CREATE FUNCTION appointment_event_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'appointment_event es append-only: % no permitido', TG_OP
    USING ERRCODE = 'integrity_constraint_violation';
END;
$$
"""


def _patient_unique() -> None:
    """UNIQUE `(id, clinic_id)` sobre `patient` sin bloquear escrituras (regla 11)."""
    with op.get_context().autocommit_block():
        op.execute(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
            f"WHERE c.relname = '{_PATIENT_UQ}' AND NOT i.indisvalid) THEN "
            f"DROP INDEX {_PATIENT_UQ}; END IF; END $$"
        )
        op.execute(
            f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {_PATIENT_UQ} "
            "ON patient (id, clinic_id)"
        )
    op.execute(f"ALTER TABLE patient ADD CONSTRAINT {_PATIENT_UQ} UNIQUE USING INDEX {_PATIENT_UQ}")


def upgrade() -> None:
    bind = op.get_bind()

    # 1. UNIQUE en `patient` para la FK compuesta intra-tenant (regla 4).
    _patient_unique()

    # 2. Enums del turno y su auditoría.
    for tipo in (*_ENUMS, ACTOR_TYPE):
        tipo.create(bind, checkfirst=False)

    # 3. Turnos (tabla nueva: constraints e índices junto con ella).
    op.create_table(
        "appointment",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("clinic_id", UUID, nullable=False),
        sa.Column("patient_id", UUID, nullable=False),
        sa.Column("professional_id", UUID, nullable=False),
        sa.Column("chair_id", UUID, nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occupied_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", APPOINTMENT_STATUS, nullable=False),
        sa.Column("origin", APPOINTMENT_ORIGIN, nullable=False),
        sa.Column("is_overbooking", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("overbooking_reason", sa.Text(), nullable=True),
        sa.Column("cancellation_reason", CANCELLATION_REASON, nullable=True),
        sa.Column("cancellation_note", sa.Text(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", UUID, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_appointment")),
        sa.UniqueConstraint("clinic_id", "id", name=op.f("uq_appointment_clinic_id_id")),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinic.id"], name=op.f("fk_appointment_clinic_id_clinic")
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "patient_id"],
            ["patient.clinic_id", "patient.id"],
            name=op.f("fk_appointment_clinic_id_patient_id_patient"),
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "professional_id"],
            ["professional.clinic_id", "professional.id"],
            name=op.f("fk_appointment_clinic_id_professional_id_professional"),
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "chair_id"],
            ["chair.clinic_id", "chair.id"],
            name=op.f("fk_appointment_clinic_id_chair_id_chair"),
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "created_by_user_id"],
            ["user.clinic_id", "user.id"],
            name=op.f("fk_appointment_clinic_id_created_by_user_id_user"),
        ),
        sa.CheckConstraint("ends_at > starts_at", name=op.f("ck_appointment_range_order")),
        sa.CheckConstraint(
            "occupied_until >= ends_at", name=op.f("ck_appointment_occupied_after_end")
        ),
        sa.CheckConstraint(
            "is_overbooking = (overbooking_reason IS NOT NULL)",
            name=op.f("ck_appointment_overbooking_reason_coherent"),
        ),
        sa.CheckConstraint(
            "origin <> 'online' OR NOT is_overbooking",
            name=op.f("ck_appointment_online_not_overbooking"),
        ),
        sa.CheckConstraint(
            "(status = 'cancelled') = (cancelled_at IS NOT NULL) "
            "AND (status = 'cancelled') = (cancellation_reason IS NOT NULL)",
            name=op.f("ck_appointment_cancellation_coherent"),
        ),
        sa.CheckConstraint(
            "cancellation_note IS NULL OR status = 'cancelled'",
            name=op.f("ck_appointment_cancellation_note_coherent"),
        ),
        sa.CheckConstraint("char_length(notes) <= 500", name=op.f("ck_appointment_notes_length")),
        sa.CheckConstraint(
            "char_length(overbooking_reason) <= 500",
            name=op.f("ck_appointment_overbooking_reason_length"),
        ),
        sa.CheckConstraint(
            "char_length(cancellation_note) <= 500",
            name=op.f("ck_appointment_cancellation_note_length"),
        ),
        sa.CheckConstraint(
            "origin <> 'reception' OR created_by_user_id IS NOT NULL",
            name=op.f("ck_appointment_reception_has_creator"),
        ),
    )
    for nombre, columna in _EXCLUDES.items():
        op.execute(
            f"ALTER TABLE appointment ADD CONSTRAINT {nombre} EXCLUDE USING gist ("
            f"clinic_id WITH =, {columna} WITH =, "
            "tstzrange(starts_at, occupied_until, '[)') WITH &&"
            f") WHERE ({_VIGENTE})"
        )
    for columnas in (("clinic_id", "starts_at"), ("professional_id", "starts_at")):
        op.create_index(op.f(f"ix_appointment_{'_'.join(columnas)}"), "appointment", columnas)
    op.create_index(
        op.f("ix_appointment_patient_id_starts_at"), "appointment", ["patient_id", "starts_at"]
    )

    # 4. Auditoría append-only (RN-GL-01).
    op.create_table(
        "appointment_event",
        sa.Column("id", UUID, server_default=GEN_UUID, nullable=False),
        sa.Column("clinic_id", UUID, nullable=False),
        sa.Column("appointment_id", UUID, nullable=False),
        sa.Column("actor_type", ACTOR_TYPE, nullable=False),
        sa.Column("actor_user_id", UUID, nullable=True),
        sa.Column("event", APPOINTMENT_EVENT_TYPE, nullable=False),
        sa.Column("from_status", APPOINTMENT_STATUS, nullable=True),
        sa.Column("to_status", APPOINTMENT_STATUS, nullable=True),
        sa.Column(
            "payload", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_appointment_event")),
        sa.ForeignKeyConstraint(
            ["clinic_id"], ["clinic.id"], name=op.f("fk_appointment_event_clinic_id_clinic")
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "appointment_id"],
            ["appointment.clinic_id", "appointment.id"],
            name=op.f("fk_appointment_event_clinic_id_appointment_id_appointment"),
        ),
        sa.ForeignKeyConstraint(
            ["clinic_id", "actor_user_id"],
            ["user.clinic_id", "user.id"],
            name=op.f("fk_appointment_event_clinic_id_actor_user_id_user"),
        ),
        sa.CheckConstraint(
            "actor_type <> 'user' OR actor_user_id IS NOT NULL",
            name=op.f("ck_appointment_event_actor_user_coherent"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'", name=op.f("ck_appointment_event_payload_is_object")
        ),
    )
    op.create_index(
        op.f("ix_appointment_event_appointment_id_created_at"),
        "appointment_event",
        ["appointment_id", "created_at"],
    )
    op.create_index(
        op.f("ix_appointment_event_clinic_id_created_at"),
        "appointment_event",
        ["clinic_id", "created_at"],
    )
    op.execute(_TRIGGER_FN)
    op.execute(
        "CREATE TRIGGER trg_appointment_event_no_mutate BEFORE UPDATE OR DELETE "
        "ON appointment_event FOR EACH ROW EXECUTE FUNCTION appointment_event_immutable()"
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.execute("DROP TRIGGER IF EXISTS trg_appointment_event_no_mutate ON appointment_event")
    op.execute("DROP FUNCTION IF EXISTS appointment_event_immutable()")
    op.drop_table("appointment_event")
    op.drop_table("appointment")
    for tipo in (ACTOR_TYPE, *reversed(_ENUMS)):
        tipo.drop(bind, checkfirst=False)
    # SQL directo: `op.drop_constraint` re-aplicaría la naming convention al nombre.
    op.execute(f"ALTER TABLE patient DROP CONSTRAINT IF EXISTS {_PATIENT_UQ}")
