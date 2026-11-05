"""Confirmar por token (C-08, D6): `pending → confirmed` con actor `patient_token`."""

from __future__ import annotations

from datetime import timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
from app.common.exceptions import DomainError
from app.models import ActorType, AppointmentEventType, AppointmentStatus, CancellationReason
from app.modules.appointments.audit import Actor
from app.modules.appointments.states import apply_transition
from sqlalchemy.ext.asyncio import AsyncSession

from tests.appointment_helpers import at, events_of, reload
from tests.conftest import AGENDA_NOW, MutableClock
from tests.manage_helpers import Managed, make_managed

pytestmark = pytest.mark.integration

CONFIRMAR = {"action": "confirm"}


async def _confirmar(client: httpx.AsyncClient, managed: Managed) -> httpx.Response:
    return await client.patch(managed.url, json=CONFIRMAR)


async def test_confirmar_un_turno_pendiente(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    managed = await make_managed(db_session, at(10, days=5))

    response = await _confirmar(app_client, managed)

    assert response.status_code == 200, response.text
    assert response.json()["appointment"]["status"] == "confirmed"
    assert response.json()["actions"]["can_confirm"] is False
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert (await reload(db_session, managed.appointment.id)).status is AppointmentStatus.CONFIRMED
    confirmados = [
        e
        for e in await events_of(db_session, managed.appointment.id)
        if e.event is AppointmentEventType.CONFIRMED
    ]
    assert len(confirmados) == 1
    evento = confirmados[0]
    assert evento.actor_type is ActorType.PATIENT_TOKEN
    assert evento.actor_user_id is None
    assert evento.from_status is AppointmentStatus.PENDING
    assert evento.payload["source"] == "manage_link"


async def test_confirmar_un_turno_ya_confirmado_no_duplica_la_transicion(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    managed = await make_managed(db_session, at(10, days=5), status=AppointmentStatus.CONFIRMED)

    response = await _confirmar(app_client, managed)

    assert response.status_code == 200
    assert response.json()["appointment"]["status"] == "confirmed"
    eventos = await events_of(db_session, managed.appointment.id)
    assert not [e for e in eventos if e.event is AppointmentEventType.CONFIRMED]


async def test_confirmar_un_turno_cancelado(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    managed = await make_managed(
        db_session,
        at(10, days=5),
        status=AppointmentStatus.CANCELLED,
        cancelled_at=AGENDA_NOW,
        cancellation_reason=CancellationReason.PACIENTE,
    )

    response = await _confirmar(app_client, managed)

    assert response.status_code == 409
    assert response.json() == {"detail": "invalid_transition"}
    assert (await reload(db_session, managed.appointment.id)).status is AppointmentStatus.CANCELLED


async def test_confirmar_un_turno_ya_empezado(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    managed = await make_managed(db_session, AGENDA_NOW - timedelta(minutes=5))

    response = await _confirmar(app_client, managed)

    assert response.status_code == 409
    assert response.json() == {"detail": "appointment_started"}
    assert (await reload(db_session, managed.appointment.id)).status is AppointmentStatus.PENDING


async def test_token_vencido_no_permite_confirmar(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    managed = await make_managed(db_session, AGENDA_NOW - timedelta(days=5))

    response = await _confirmar(app_client, managed)

    assert response.status_code == 410
    assert (await reload(db_session, managed.appointment.id)).status is AppointmentStatus.PENDING


@pytest.mark.parametrize(
    "destino", [AppointmentStatus.PRESENT, AppointmentStatus.ABSENT, AppointmentStatus.NO_SHOW]
)
async def test_el_token_no_puede_marcar_asistencia(
    db_session: AsyncSession, agenda_clock: MutableClock, destino: AppointmentStatus
) -> None:
    """La máquina de estados rechaza asistencia pedida por un `patient_token` (sin roles)."""
    managed = await make_managed(
        db_session, AGENDA_NOW - timedelta(minutes=5), status=AppointmentStatus.CONFIRMED
    )
    actor = Actor(clinic_id=managed.booking.clinic.id, type=ActorType.PATIENT_TOKEN)

    with pytest.raises(DomainError) as error:
        await apply_transition(
            db_session,
            managed.appointment,
            destino,
            actor,
            now=AGENDA_NOW,
            tz=ZoneInfo("America/Argentina/Buenos_Aires"),
            cancellation_window_hours=24,
        )

    assert (error.value.status_code, error.value.detail) == (409, "invalid_transition")
    assert managed.appointment.status is AppointmentStatus.CONFIRMED
