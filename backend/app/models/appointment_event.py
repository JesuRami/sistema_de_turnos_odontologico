"""Auditoría append-only de turnos (C-05, RN-GL-01).

Igual que `auth_event` y `agenda_config_event`, la inmutabilidad la impone un
trigger `BEFORE UPDATE OR DELETE`. El evento se escribe en la misma transacción
que la mutación. `payload` lleva antes/después, ids de colisión y motivos;
nunca nombre, teléfono ni email del paciente (regla 13).
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
        CheckConstraint(
            "actor_type <> 'user' OR actor_user_id IS NOT NULL", name="actor_user_coherent"
        ),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_is_object"),
        Index(None, "appointment_id", "created_at"),
        Index(None, "clinic_id", "created_at"),
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
    # `clock_timestamp()` (no `now()`): ordena también los eventos de una misma transacción.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()"), nullable=False
    )
