"""Auditoría append-only de turnos (C-05, RN-GL-01).

Igual que `auth_event` y `agenda_config_event`, la inmutabilidad la impone un
trigger `BEFORE UPDATE OR DELETE`. El evento se escribe en la misma transacción
que la mutación. `payload` lleva antes/después, ids de colisión y motivos;
nunca nombre, teléfono ni email del paciente (regla 13).

Desde C-13 cada evento nuevo sella la instantánea del turno (`slot_starts_at`,
`slot_ends_at`, `professional_id`, `chair_id`): el último evento de un turno
describe su horario y recursos finales sin leer `appointment`, que es lo que
usan los reportes (US-050 CA-3). Los eventos anteriores quedan con NULL.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Index, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.appointment import APPOINTMENT_STATUS, pg_enum
from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.enums import ActorType, AppointmentEventType, AppointmentStatus


class AppointmentEvent(UUIDPrimaryKeyMixin, Base):
    """Traza inmutable de una mutación de turno (sin `updated_at`)."""

    __tablename__ = "appointment_event"
    __table_args__ = (
        ForeignKeyConstraint(["clinic_id"], ["clinic.id"]),
        ForeignKeyConstraint(
            ["clinic_id", "appointment_id"], ["appointment.clinic_id", "appointment.id"]
        ),
        ForeignKeyConstraint(["clinic_id", "actor_user_id"], ["user.clinic_id", "user.id"]),
        ForeignKeyConstraint(
            ["clinic_id", "professional_id"], ["professional.clinic_id", "professional.id"]
        ),
        ForeignKeyConstraint(["clinic_id", "chair_id"], ["chair.clinic_id", "chair.id"]),
        CheckConstraint(
            "(slot_starts_at IS NULL AND slot_ends_at IS NULL "
            "AND professional_id IS NULL AND chair_id IS NULL) "
            "OR (slot_starts_at IS NOT NULL AND slot_ends_at IS NOT NULL "
            "AND professional_id IS NOT NULL AND chair_id IS NOT NULL "
            "AND slot_ends_at > slot_starts_at)",
            name="slot_coherent",
        ),
        CheckConstraint(
            "actor_type <> 'user' OR actor_user_id IS NOT NULL", name="actor_user_coherent"
        ),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_is_object"),
        Index(None, "appointment_id", "created_at"),
        Index(None, "clinic_id", "created_at"),
        Index(None, "clinic_id", "slot_starts_at"),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    appointment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_type: Mapped[ActorType] = mapped_column(pg_enum(ActorType, "actor_type"), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    event: Mapped[AppointmentEventType] = mapped_column(
        pg_enum(AppointmentEventType, "appointment_event_type"), nullable=False
    )
    from_status: Mapped[AppointmentStatus | None] = mapped_column(APPOINTMENT_STATUS, nullable=True)
    to_status: Mapped[AppointmentStatus | None] = mapped_column(APPOINTMENT_STATUS, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    slot_starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    slot_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    professional_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    chair_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # `clock_timestamp()` (no `now()`): ordena también los eventos de una misma transacción.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()"), nullable=False
    )
