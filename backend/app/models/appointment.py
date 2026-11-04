"""Turno de la clínica (C-05, RN-AG-01/04, RN-SB-01, RN-ST-01).

Invariante central (regla dura 1): dos turnos vigentes no sobreturno nunca
comparten profesional ni sillón con rangos ocupados intersectados. La impone la
base con dos `EXCLUDE USING gist` sobre `tstzrange(starts_at, occupied_until)`.
`occupied_until` = `ends_at` + buffer del profesional, guardado como snapshot al
crear o reprogramar (una columna generada no puede: `timestamptz + interval` no
es inmutable y el buffer vive en otra tabla). Sin borrado físico (regla 7).
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    Text,
    UniqueConstraint,
    literal_column,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import AppointmentOrigin, AppointmentStatus, CancellationReason

TEXT_MAX_LENGTH = 500
OCCUPIED_RANGE_SQL = "tstzrange(starts_at, occupied_until, '[)')"
# Vigente = ocupa agenda (RN-AG-01). `absent` libera el recurso (US-013 CA-2).
VIGENT_PREDICATE_SQL = "status IN ('pending', 'confirmed', 'present') AND NOT is_overbooking"


def pg_enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    """Enum nativo de Postgres creado por la migración (no por `create_all`)."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=True,
        create_type=False,
        values_callable=lambda valores: [v.value for v in valores],
    )


APPOINTMENT_STATUS = pg_enum(AppointmentStatus, "appointment_status")


class Appointment(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """Turno `[starts_at, ends_at)`; ocupa la agenda hasta `occupied_until`."""

    __tablename__ = "appointment"
    __table_args__ = (
        # Habilita la FK compuesta de `appointment_event` (regla 4).
        UniqueConstraint("clinic_id", "id"),
        ForeignKeyConstraint(["clinic_id", "patient_id"], ["patient.clinic_id", "patient.id"]),
        ForeignKeyConstraint(
            ["clinic_id", "professional_id"], ["professional.clinic_id", "professional.id"]
        ),
        ForeignKeyConstraint(["clinic_id", "chair_id"], ["chair.clinic_id", "chair.id"]),
        ForeignKeyConstraint(["clinic_id", "created_by_user_id"], ["user.clinic_id", "user.id"]),
        CheckConstraint("ends_at > starts_at", name="range_order"),
        CheckConstraint("occupied_until >= ends_at", name="occupied_after_end"),
        CheckConstraint(
            "is_overbooking = (overbooking_reason IS NOT NULL)", name="overbooking_reason_coherent"
        ),
        # RN-SB-01: un turno online nunca es sobreturno, también en la base.
        CheckConstraint("origin <> 'online' OR NOT is_overbooking", name="online_not_overbooking"),
        CheckConstraint(
            "(status = 'cancelled') = (cancelled_at IS NOT NULL) "
            "AND (status = 'cancelled') = (cancellation_reason IS NOT NULL)",
            name="cancellation_coherent",
        ),
        CheckConstraint(
            "cancellation_note IS NULL OR status = 'cancelled'", name="cancellation_note_coherent"
        ),
        CheckConstraint(f"char_length(notes) <= {TEXT_MAX_LENGTH}", name="notes_length"),
        CheckConstraint(
            f"char_length(overbooking_reason) <= {TEXT_MAX_LENGTH}",
            name="overbooking_reason_length",
        ),
        CheckConstraint(
            f"char_length(cancellation_note) <= {TEXT_MAX_LENGTH}",
            name="cancellation_note_length",
        ),
        CheckConstraint(
            "origin <> 'reception' OR created_by_user_id IS NOT NULL",
            name="reception_has_creator",
        ),
        # C-07 (D8): solo el SHA-256 del token de gestión; todo turno online lo lleva.
        CheckConstraint(
            "manage_token_hash IS NULL OR octet_length(manage_token_hash) = 32",
            name="manage_token_hash_length",
        ),
        CheckConstraint(
            "origin <> 'online' OR manage_token_hash IS NOT NULL", name="online_has_manage_token"
        ),
        Index(
            "uq_appointment_manage_token_hash",
            "manage_token_hash",
            unique=True,
            postgresql_where=text("manage_token_hash IS NOT NULL"),
        ),
        Index(None, "clinic_id", "starts_at"),
        Index(None, "professional_id", "starts_at"),
        Index(None, "patient_id", "starts_at"),
        ExcludeConstraint(
            ("clinic_id", "="),
            ("professional_id", "="),
            (literal_column(OCCUPIED_RANGE_SQL), "&&"),
            name="ex_appointment_professional_no_overlap",
            using="gist",
            where=text(VIGENT_PREDICATE_SQL),
        ),
        ExcludeConstraint(
            ("clinic_id", "="),
            ("chair_id", "="),
            (literal_column(OCCUPIED_RANGE_SQL), "&&"),
            name="ex_appointment_chair_no_overlap",
            using="gist",
            where=text(VIGENT_PREDICATE_SQL),
        ),
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    professional_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    chair_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    occupied_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[AppointmentStatus] = mapped_column(APPOINTMENT_STATUS, nullable=False)
    origin: Mapped[AppointmentOrigin] = mapped_column(
        pg_enum(AppointmentOrigin, "appointment_origin"), nullable=False
    )
    is_overbooking: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    overbooking_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancellation_reason: Mapped[CancellationReason | None] = mapped_column(
        pg_enum(CancellationReason, "cancellation_reason"), nullable=True
    )
    cancellation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Notas operativas de recepción; nunca clínicas (la historia clínica llega en C-15).
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # SHA-256 (32 bytes) del token de gestión del paciente; el token en claro no se guarda.
    manage_token_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
