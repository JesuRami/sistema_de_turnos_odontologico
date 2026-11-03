"""Escenario sintético de turnos (C-05): clínica, roles, plantilla del lunes y un paciente.

El reloj de la app está fijo en `AGENDA_NOW` (lunes 2030-01-07 08:00 Buenos
Aires) vía la fixture `agenda_clock`. La plantilla es lunes 09:00-13:00 con
slots de 30 min. Todo dato es ficticio (regla 13).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from app.core.settings import Settings
from app.models import (
    Appointment,
    AppointmentEvent,
    Patient,
    ScheduleRule,
)
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.agenda_helpers import Staff, make_staff
from tests.factories import make_appointment, make_patient, make_schedule_rule

BA = ZoneInfo("America/Argentina/Buenos_Aires")
LUNES = date(2030, 1, 7)
PACIENTE_NOMBRE = "Paciente Ficticio Agenda"


def at(hh: int, mm: int = 0, *, days: int = 0) -> datetime:
    """Instante local de Buenos Aires `LUNES + days` a las `hh:mm`."""
    return datetime.combine(LUNES + timedelta(days=days), time(hh, mm), tzinfo=BA)


def iso(hh: int, mm: int = 0, *, days: int = 0) -> str:
    return at(hh, mm, days=days).isoformat()


@dataclass(frozen=True, slots=True)
class Agenda:
    """`Staff` de C-04 + regla del lunes + un paciente."""

    staff: Staff
    patient: Patient
    rule: ScheduleRule

    @property
    def headers(self) -> dict[str, dict[str, str]]:
        return self.staff.headers


async def make_agenda(
    db_session: AsyncSession, redis_client: Redis, settings: Settings, **rule: Any
) -> Agenda:
    staff = await make_staff(db_session, redis_client, settings)
    regla = await make_schedule_rule(
        db_session, staff.clinic, staff.professional, staff.chair, **rule
    )
    patient = await make_patient(db_session, staff.clinic, full_name=PACIENTE_NOMBRE)
    return Agenda(staff=staff, patient=patient, rule=regla)


def body(agenda: Agenda, starts_at: datetime | str, **overrides: Any) -> dict[str, Any]:
    valores: dict[str, Any] = {
        "patient_id": str(agenda.patient.id),
        "professional_id": str(agenda.staff.professional.id),
        "chair_id": str(agenda.staff.chair.id),
        "starts_at": starts_at if isinstance(starts_at, str) else starts_at.isoformat(),
    }
    valores.update(overrides)
    return valores


async def post(
    client: httpx.AsyncClient,
    agenda: Agenda,
    starts_at: datetime | str,
    rol: str = "recepcion",
    /,
    **overrides: Any,
) -> httpx.Response:
    return await client.post(
        "/api/appointments", json=body(agenda, starts_at, **overrides), headers=agenda.headers[rol]
    )


async def seed(
    db_session: AsyncSession, agenda: Agenda, starts_at: datetime, **overrides: Any
) -> Appointment:
    """Turno persistido directo (sin servicio) sobre el profesional y sillón del escenario."""
    valores: dict[str, Any] = {
        "patient": agenda.patient,
        "professional": agenda.staff.professional,
        "chair": agenda.staff.chair,
        "created_by_user_id": agenda.staff.admin.id,
    }
    valores.update(overrides)
    return await make_appointment(db_session, agenda.staff.clinic, starts_at=starts_at, **valores)


async def events_of(db_session: AsyncSession, appointment_id: uuid.UUID) -> list[AppointmentEvent]:
    stmt = (
        select(AppointmentEvent)
        .where(AppointmentEvent.appointment_id == appointment_id)
        .order_by(AppointmentEvent.created_at, AppointmentEvent.id)
    )
    return list((await db_session.execute(stmt)).scalars().all())


async def reload(db_session: AsyncSession, appointment_id: uuid.UUID) -> Appointment:
    """Relee el turno desde la base (descarta el estado en memoria)."""
    db_session.expire_all()
    encontrado = await db_session.get(Appointment, appointment_id)
    assert encontrado is not None
    return encontrado
