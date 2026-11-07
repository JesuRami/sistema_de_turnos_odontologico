"""Carga del turno y su contexto de recordatorios con el alcance del actor (C-11, D3/D4).

El alcance es el mismo que `AppointmentsService._scoped`: la clínica del actor y, si es solo
odontólogo, su `professional_id`, en SQL. Un turno fuera de alcance es `404 not_found`. Todas las
consultas seleccionan columnas explícitas (regla 8) y filtran por `clinic_id` (regla 4). Los datos
del paciente solo se usan para decidir guardas: nunca salen en la respuesta ni en logs (regla 13).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import DomainError
from app.models import (
    Appointment,
    AppointmentOrigin,
    AppointmentStatus,
    Clinic,
    ConsentStatus,
    Patient,
    ReminderChannel,
)
from app.modules.appointments.audit import Actor
from app.modules.reminders.consent import ConsentService
from app.modules.reminders.guards import ResendContext
from app.modules.reminders.scheduling import configured_step_names


@dataclass(frozen=True, slots=True)
class ScopedAppointment:
    id: uuid.UUID
    clinic_id: uuid.UUID
    patient_id: uuid.UUID
    status: AppointmentStatus
    origin: AppointmentOrigin
    starts_at: datetime


async def scoped_appointment(
    session: AsyncSession, actor: Actor, appointment_id: uuid.UUID, *, lock: bool = False
) -> ScopedAppointment:
    stmt: Any = select(
        Appointment.id,
        Appointment.clinic_id,
        Appointment.patient_id,
        Appointment.status,
        Appointment.origin,
        Appointment.starts_at,
    ).where(Appointment.clinic_id == actor.clinic_id, Appointment.id == appointment_id)
    if actor.only_dentist:
        if actor.professional_id is None:
            raise DomainError(403, "forbidden_scope")
        stmt = stmt.where(Appointment.professional_id == actor.professional_id)
    if lock:
        stmt = stmt.with_for_update(of=Appointment)
    fila = (await session.execute(stmt)).one_or_none()
    if fila is None:
        raise DomainError(404, "not_found")
    return ScopedAppointment(
        id=fila.id,
        clinic_id=fila.clinic_id,
        patient_id=fila.patient_id,
        status=fila.status,
        origin=fila.origin,
        starts_at=fila.starts_at,
    )


async def resend_context(session: AsyncSession, turno: ScopedAppointment) -> ResendContext:
    clinica = (
        await session.execute(
            select(Clinic.timezone, Clinic.reminder_steps).where(Clinic.id == turno.clinic_id)
        )
    ).one()
    paciente = (
        await session.execute(
            select(Patient.whatsapp_opt_in, Patient.phone_e164, Patient.email).where(
                Patient.clinic_id == turno.clinic_id, Patient.id == turno.patient_id
            )
        )
    ).one()
    baja_email = (
        await ConsentService(session).current(
            turno.clinic_id, turno.patient_id, ReminderChannel.EMAIL
        )
        is ConsentStatus.OPT_OUT
    )
    return ResendContext(
        appointment_status=turno.status,
        origin=turno.origin,
        starts_at=turno.starts_at,
        configured_steps=configured_step_names(list(clinica.reminder_steps or [])),
        whatsapp_opt_in=bool(paciente.whatsapp_opt_in),
        has_phone=bool((paciente.phone_e164 or "").strip()),
        has_email=bool((paciente.email or "").strip()),
        email_opted_out=baja_email,
        tz=ZoneInfo(clinica.timezone),
    )
