"""Acciones del paciente compartidas por el link de gestión (C-08) y WhatsApp (C-10, D7).

C-08 dejó el contrato "C-10 reutiliza ManageService/apply_transition con un actor de paciente":
esta función es esa pieza común, con las mismas guardas, para que el "SÍ" por WhatsApp y el
botón de la página de gestión no diverjan. Corre en la transacción del llamador (sin commit).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import DomainError
from app.models import ActorType, Appointment, AppointmentEventType, AppointmentStatus
from app.modules.appointments.audit import Actor, record_event
from app.modules.appointments.states import apply_transition


class ConfirmOutcome(enum.Enum):
    CONFIRMED = "confirmed"
    REPLAYED = "replayed"


def patient_actor(clinic_id: uuid.UUID) -> Actor:
    return Actor(clinic_id=clinic_id, type=ActorType.PATIENT_TOKEN)


async def lock_appointment(
    session: AsyncSession, clinic_id: uuid.UUID, appointment_id: uuid.UUID
) -> Appointment:
    """El turno con `FOR UPDATE`: dos acciones simultáneas sobre él se serializan."""
    appointment: Appointment = (
        await session.execute(
            select(Appointment)
            .where(Appointment.id == appointment_id, Appointment.clinic_id == clinic_id)
            .with_for_update()
        )
    ).scalar_one()
    return appointment


async def record_replay(
    session: AsyncSession, appointment: Appointment, *, action: str, source: str
) -> None:
    """Acción ya aplicada: evento `updated` auditable, sin repetir la transición (C-08 D9)."""
    await record_event(
        session,
        patient_actor(appointment.clinic_id),
        appointment,
        AppointmentEventType.UPDATED,
        from_status=appointment.status,
        to_status=appointment.status,
        payload={"idempotent_replay": True, "action": action, "source": source},
    )


async def confirm_by_patient(
    session: AsyncSession,
    *,
    clinic_id: uuid.UUID,
    appointment_id: uuid.UUID,
    now: datetime,
    tz: ZoneInfo,
    cancellation_window_hours: int,
    source: str,
) -> ConfirmOutcome:
    """`pending → confirmed` por el paciente; ya confirmado es un no-op auditado.

    Turno iniciado → `409 appointment_started`; un estado no confirmable → el `409` de la
    máquina de estados. La transición reconcilia los recordatorios (C-09 D3).
    """
    appointment = await lock_appointment(session, clinic_id, appointment_id)
    if now >= appointment.starts_at:
        raise DomainError(409, "appointment_started")
    if appointment.status is AppointmentStatus.CONFIRMED:
        await record_replay(session, appointment, action="confirm", source=source)
        return ConfirmOutcome.REPLAYED
    await apply_transition(
        session,
        appointment,
        AppointmentStatus.CONFIRMED,
        patient_actor(clinic_id),
        now=now,
        tz=tz,
        cancellation_window_hours=cancellation_window_hours,
        extra_payload={"source": source},
    )
    return ConfirmOutcome.CONFIRMED
