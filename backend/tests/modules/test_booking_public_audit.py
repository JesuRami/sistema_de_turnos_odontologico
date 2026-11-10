"""Auditoría de la reserva pública (C-07, D9): evento `created` sin PII y atomicidad."""

from __future__ import annotations

import json

import httpx
import pytest
from app.core.settings import Settings
from app.models import (
    ActorType,
    Appointment,
    AppointmentEvent,
    AppointmentEventType,
    Patient,
)
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.appointment_helpers import iso
from tests.booking_helpers import (
    EMAIL,
    NOMBRE,
    PublicBooking,
    client_for,
    committed_app,
    make_booking,
    reserva,
)
from tests.conftest import MutableClock

pytestmark = pytest.mark.integration


def _url(b: PublicBooking) -> str:
    return f"/api/booking/{b.slug}/appointments"


async def test_el_turno_online_tiene_un_evento_created_del_paciente_sin_pii(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    b = await make_booking(db_session)

    response = await app_client.post(_url(b), json=reserva(b, iso(10), email=EMAIL))

    assert response.status_code == 201, response.text
    turno = (
        await db_session.execute(select(Appointment).where(Appointment.clinic_id == b.clinic.id))
    ).scalar_one()
    (evento,) = (
        await db_session.execute(
            select(AppointmentEvent).where(AppointmentEvent.appointment_id == turno.id)
        )
    ).scalars()
    assert evento.event == AppointmentEventType.CREATED
    assert evento.actor_type == ActorType.PATIENT_TOKEN
    assert evento.actor_user_id is None
    assert evento.payload["origin"] == "online"
    assert evento.payload["channel"] == "whatsapp"
    assert evento.payload["whatsapp_opt_in_granted"] is True
    crudo = json.dumps(evento.payload)
    for dato in (NOMBRE, "Lucía", "5555", EMAIL, "lucia", settings.FRONTEND_PUBLIC_URL):
        assert dato not in crudo, dato


async def test_el_canal_email_queda_en_el_evento(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)

    response = await app_client.post(
        _url(b), json=reserva(b, iso(10), whatsapp_opt_in=False, email=EMAIL)
    )

    assert response.status_code == 201, response.text
    evento = (await db_session.execute(select(AppointmentEvent))).scalars().one()
    assert evento.payload["channel"] == "email"
    assert evento.payload["whatsapp_opt_in_granted"] is False


async def test_una_falla_al_escribir_el_evento_revierte_turno_y_paciente_nuevo(
    committed_engine: AsyncEngine,
    redis_client: Redis,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AsyncSession(committed_engine, expire_on_commit=False) as session:
        b = await make_booking(session)
        await session.commit()
    app = committed_app(committed_engine, redis_client, settings)

    async def _falla(*args: object, **kwargs: object) -> None:
        raise RuntimeError("falla inyectada al escribir el evento")

    monkeypatch.setattr("app.modules.appointments.service.record_event", _falla)

    async with client_for(app) as client:
        res = await client.post(_url(b), json=reserva(b, iso(10)))
        assert res.status_code == 500

    async with AsyncSession(committed_engine) as session:
        pacientes = await session.scalar(select(func.count()).select_from(Patient))
        turnos = await session.scalar(select(func.count()).select_from(Appointment))
    assert (pacientes, turnos) == (0, 0)
