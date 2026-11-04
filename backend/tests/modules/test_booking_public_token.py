"""Token de gestión (C-07, D8): 256 bits, solo el SHA-256 persiste, nunca en eventos ni logs."""

from __future__ import annotations

import hashlib
import logging
import re

import httpx
import pytest
from app.core.settings import Settings
from app.models import Appointment, AppointmentEvent, UserRole
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.appointment_helpers import at, iso
from tests.auth_helpers import issue_session
from tests.booking_helpers import PublicBooking, make_booking, reserva
from tests.conftest import MutableClock
from tests.factories import make_user, unique_email

pytestmark = pytest.mark.integration

URL_SAFE = re.compile(r"^[A-Za-z0-9_-]{43,}$")


def _url(b: PublicBooking) -> str:
    return f"/api/booking/{b.slug}/appointments"


def _token(response: httpx.Response, settings: Settings) -> str:
    prefijo = f"{settings.FRONTEND_PUBLIC_URL}/g/"
    manage_url = response.json()["manage_url"]
    assert manage_url.startswith(prefijo)
    return str(manage_url.removeprefix(prefijo))


async def test_el_201_trae_el_link_de_gestion_con_cabeceras_de_no_cache(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    b = await make_booking(db_session)

    response = await app_client.post(_url(b), json=reserva(b, iso(10)))

    assert response.status_code == 201, response.text
    assert URL_SAFE.match(_token(response, settings))
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"


async def test_la_base_guarda_solo_el_sha256_y_el_token_no_aparece_en_ningun_lado(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    b = await make_booking(db_session)
    recepcion = await make_user(
        db_session,
        b.clinic,
        email=unique_email("recepcion.ficticia"),
        role=UserRole.RECEPCION,
        must_change_password=False,
    )
    headers = (await issue_session(redis_client, settings, recepcion)).headers

    response = await app_client.post(_url(b), json=reserva(b, iso(10)))

    assert response.status_code == 201, response.text
    token = _token(response, settings)
    turno = (
        await db_session.execute(select(Appointment).where(Appointment.clinic_id == b.clinic.id))
    ).scalar_one()
    # Verdad independiente: el hash esperado se calcula en el test con hashlib.
    assert turno.manage_token_hash == hashlib.sha256(token.encode()).digest()
    assert len(turno.manage_token_hash) == 32
    fila = (
        await db_session.execute(
            text("SELECT a::text FROM appointment a WHERE a.id = :id"), {"id": turno.id}
        )
    ).scalar_one()
    assert token not in fila
    eventos = (
        await db_session.execute(
            select(AppointmentEvent.payload).where(AppointmentEvent.appointment_id == turno.id)
        )
    ).scalars()
    for payload in eventos:
        assert token not in str(payload)
        assert "manage" not in str(payload)
    assert token not in caplog.text
    agenda = await app_client.get(
        "/api/appointments",
        params={"from": at(0).isoformat(), "to": at(0, days=1).isoformat()},
        headers=headers,
    )
    assert token not in agenda.text
    assert "manage_token" not in agenda.text


async def test_dos_reservas_reciben_tokens_distintos(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    b = await make_booking(db_session)

    primera = await app_client.post(_url(b), json=reserva(b, iso(10)))
    segunda = await app_client.post(_url(b), json=reserva(b, iso(10, 30)))

    assert (primera.status_code, segunda.status_code) == (201, 201)
    assert _token(primera, settings) != _token(segunda, settings)
    hashes = (await db_session.execute(select(Appointment.manage_token_hash))).scalars().all()
    assert len(set(hashes)) == 2
