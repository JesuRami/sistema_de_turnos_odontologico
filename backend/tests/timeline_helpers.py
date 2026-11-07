"""Escenarios del timeline y de las acciones manuales de recordatorios (C-11).

Clínica con sesiones por rol (`make_staff`), turnos, jobs y eventos sembrados directo, como los
escribirían el motor y el webhook. El reloj de la app está fijo en `AGENDA_NOW` (fixture
`agenda_clock`). Todo dato es ficticio (regla 13): teléfonos `+54 11 5555-01xx`, emails
`@example.com`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.core.settings import Settings
from app.models import (
    Appointment,
    AppointmentOrigin,
    AppointmentStatus,
    DeliveryEvent,
    DeliveryEventType,
    Patient,
    Professional,
    ReminderChannel,
    ReminderJob,
    ReminderManualResend,
    ReminderStatus,
    User,
    UserRole,
)
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.agenda_helpers import Staff, make_staff
from tests.conftest import AGENDA_NOW
from tests.factories import (
    make_appointment,
    make_patient,
    make_professional,
    unique_email,
    unique_phone_e164,
)

NOW = AGENDA_NOW
W = ReminderChannel.WHATSAPP
E = ReminderChannel.EMAIL
PACIENTE = "Paciente Timeline Ficticio"


@dataclass(frozen=True, slots=True)
class Escena:
    staff: Staff
    patient: Patient
    appointment: Appointment
    recepcion: User

    @property
    def headers(self) -> dict[str, dict[str, str]]:
        return self.staff.headers


async def escena(
    db: AsyncSession,
    redis: Redis,
    settings: Settings,
    *,
    starts_in: timedelta = timedelta(days=3),
    status: AppointmentStatus = AppointmentStatus.CONFIRMED,
    origin: AppointmentOrigin = AppointmentOrigin.RECEPTION,
    opt_in: bool = True,
    email: str | None = "",
    staff: Staff | None = None,
    professional: Professional | None = None,
) -> Escena:
    staff = staff or await make_staff(db, redis, settings)
    paciente = await make_patient(
        db,
        staff.clinic,
        full_name=PACIENTE,
        phone_e164=unique_phone_e164(),
        email=unique_email("paciente.timeline") if email == "" else email,
        whatsapp_opt_in=opt_in,
    )
    turno = await make_appointment(
        db,
        staff.clinic,
        patient=paciente,
        professional=professional or staff.professional,
        chair=staff.chair,
        starts_at=NOW + starts_in,
        status=status,
        origin=origin,
    )
    recepcion = await db.scalar(
        select(User).where(User.clinic_id == staff.clinic.id, User.role == UserRole.RECEPCION)
    )
    assert recepcion is not None
    return Escena(staff, paciente, turno, recepcion)


async def otro_profesional(db: AsyncSession, staff: Staff) -> Professional:
    return await make_professional(db, staff.clinic)


async def job(
    db: AsyncSession,
    turno: Appointment,
    step: str = "t_24h",
    channel: ReminderChannel = W,
    status: ReminderStatus = ReminderStatus.SENT,
    **overrides: Any,
) -> ReminderJob:
    horas = {"created": 0, "t_72h": 72, "t_24h": 24, "t_3h": 3}.get(step, 24)
    cuando = turno.starts_at - timedelta(hours=horas) if step != "created" else NOW
    valores: dict[str, Any] = {
        "clinic_id": turno.clinic_id,
        "appointment_id": turno.id,
        "step": step,
        "channel": channel,
        "scheduled_for": cuando,
        "available_at": cuando,
        "starts_at_snapshot": turno.starts_at,
        "status": status,
    }
    if status in (ReminderStatus.SENT, ReminderStatus.DELIVERED, ReminderStatus.READ):
        valores.setdefault("sent_at", cuando)
    if status is ReminderStatus.SENDING:
        valores.setdefault("claimed_at", cuando)
    valores.update(overrides)
    fila = ReminderJob(**valores)
    db.add(fila)
    await db.flush()
    return fila


async def evento(
    db: AsyncSession,
    fila: ReminderJob,
    tipo: DeliveryEventType,
    momento: datetime,
    **payload: Any,
) -> DeliveryEvent:
    nuevo = DeliveryEvent(
        clinic_id=fila.clinic_id,
        reminder_job_id=fila.id,
        event_type=tipo,
        payload=payload,
        occurred_at=momento,
    )
    db.add(nuevo)
    await db.flush()
    return nuevo


async def reenvio(
    db: AsyncSession, fila: ReminderJob, actor: User, momento: datetime, note: str | None = None
) -> ReminderManualResend:
    nuevo = ReminderManualResend(
        clinic_id=fila.clinic_id,
        appointment_id=fila.appointment_id,
        reminder_job_id=fila.id,
        actor_user_id=actor.id,
        note=note,
        created_at=momento,
    )
    db.add(nuevo)
    await db.flush()
    return nuevo


async def resends_of(db: AsyncSession, job_id: uuid.UUID) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(ReminderManualResend)
            .where(ReminderManualResend.reminder_job_id == job_id)
        )
        or 0
    )


def timeline_url(appointment_id: uuid.UUID) -> str:
    return f"/api/appointments/{appointment_id}/reminders"


def resend_url(appointment_id: uuid.UUID, step: str = "t_24h", channel: str = "whatsapp") -> str:
    return f"/api/appointments/{appointment_id}/reminders/{step}/{channel}/resend"
