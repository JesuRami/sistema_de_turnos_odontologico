"""Actor y auditoría de turnos (C-05, D7, RN-GL-01).

El evento se agrega a la sesión de la mutación y se hace `flush` en el acto:
si la base lo rechaza, la operación entera falla y nada se confirma.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.principal import Principal
from app.models import (
    ActorType,
    Appointment,
    AppointmentEvent,
    AppointmentEventType,
    AppointmentStatus,
    UserRole,
)
from app.modules.agenda.audit import to_json


@dataclass(frozen=True, slots=True)
class Actor:
    """Quién muta un turno: personal (desde el `Principal`), token de paciente o sistema."""

    clinic_id: uuid.UUID
    type: ActorType
    user_id: uuid.UUID | None = None
    roles: frozenset[UserRole] = field(default_factory=frozenset)
    professional_id: uuid.UUID | None = None

    @classmethod
    def from_principal(cls, principal: Principal) -> Actor:
        return cls(
            clinic_id=principal.clinic_id,
            type=ActorType.USER,
            user_id=principal.user_id,
            roles=principal.roles,
            professional_id=principal.professional_id,
        )

    @property
    def is_admin(self) -> bool:
        return UserRole.ADMIN in self.roles

    @property
    def is_front_desk(self) -> bool:
        """Admin o recepción: pueden crear, cancelar y sobreturnar."""
        return bool(self.roles & {UserRole.ADMIN, UserRole.RECEPCION})

    @property
    def only_dentist(self) -> bool:
        return self.roles == {UserRole.ODONTOLOGO}


def slot_snapshot(appointment: Appointment) -> dict[str, Any]:
    """Columnas de instantánea de `appointment_event` (C-13): solo ids y fechas, sin PII."""
    return {
        "slot_starts_at": appointment.starts_at,
        "slot_ends_at": appointment.ends_at,
        "professional_id": appointment.professional_id,
        "chair_id": appointment.chair_id,
    }


async def record_event(
    session: AsyncSession,
    actor: Actor,
    appointment: Appointment,
    event: AppointmentEventType,
    *,
    from_status: AppointmentStatus | None,
    to_status: AppointmentStatus | None,
    payload: dict[str, Any],
) -> None:
    """Inserta el evento en la transacción en curso (sin commit propio)."""
    session.add(
        AppointmentEvent(
            clinic_id=appointment.clinic_id,
            appointment_id=appointment.id,
            actor_type=actor.type,
            actor_user_id=actor.user_id,
            event=event,
            from_status=from_status,
            to_status=to_status,
            payload=to_json(payload),
            **slot_snapshot(appointment),
        )
    )
    await session.flush()
