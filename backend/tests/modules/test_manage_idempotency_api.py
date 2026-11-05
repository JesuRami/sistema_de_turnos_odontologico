"""Idempotencia por estado (C-08, D9): repetir una acción es un no-op auditado."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from app.core.settings import Settings
from app.models import AppointmentEventType, AppointmentStatus, UserRole
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tests.appointment_helpers import at, events_of
from tests.auth_helpers import issue_session
from tests.conftest import MutableClock
from tests.factories import make_user, unique_email
from tests.manage_helpers import Managed, make_managed
from tests.report_helpers import DIA, rango

pytestmark = pytest.mark.integration

LUNES_DIA = 7  # `DIA` de report_helpers = AGENDA_NOW + 7 días


async def _accion(client: httpx.AsyncClient, managed: Managed, **body: Any) -> httpx.Response:
    return await client.patch(managed.url, json=body)


async def _eventos(
    db_session: AsyncSession, appointment_id: uuid.UUID
) -> dict[AppointmentEventType, list[Any]]:
    agrupados: dict[AppointmentEventType, list[Any]] = {}
    for evento in await events_of(db_session, appointment_id):
        agrupados.setdefault(evento.event, []).append(evento)
    return agrupados


def _replay_de(eventos: dict[AppointmentEventType, list[Any]], accion: str) -> Any:
    replays = [
        e
        for e in eventos.get(AppointmentEventType.UPDATED, [])
        if e.payload.get("idempotent_replay")
    ]
    assert len(replays) == 1
    assert replays[0].payload["action"] == accion
    return replays[0]


async def test_doble_confirmacion(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    managed = await make_managed(db_session, at(10, days=LUNES_DIA))
    appointment_id = managed.appointment.id

    primera = await _accion(app_client, managed, action="confirm")
    segunda = await _accion(app_client, managed, action="confirm")

    assert (primera.status_code, segunda.status_code) == (200, 200)
    assert segunda.json()["appointment"]["status"] == "confirmed"
    eventos = await _eventos(db_session, appointment_id)
    assert len(eventos[AppointmentEventType.CONFIRMED]) == 1
    replay = _replay_de(eventos, "confirm")
    assert (replay.from_status, replay.to_status) == (
        AppointmentStatus.CONFIRMED,
        AppointmentStatus.CONFIRMED,
    )
    assert replay.actor_user_id is None


async def test_doble_cancelacion_no_cuenta_dos_veces_en_el_reporte(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    managed = await make_managed(db_session, at(10, days=LUNES_DIA))
    appointment_id = managed.appointment.id
    admin = await make_user(
        db_session,
        managed.booking.clinic,
        email=unique_email("admin.ficticio"),
        role=UserRole.ADMIN,
        must_change_password=False,
    )
    headers = (await issue_session(redis_client, settings, admin)).headers

    primera = await _accion(app_client, managed, action="cancel", reason="viaje")
    segunda = await _accion(app_client, managed, action="cancel", reason="viaje")

    assert (primera.status_code, segunda.status_code) == (200, 200)
    assert segunda.json()["appointment"]["status"] == "cancelled"
    eventos = await _eventos(db_session, appointment_id)
    assert len(eventos[AppointmentEventType.CANCELLED]) == 1
    _replay_de(eventos, "cancel")
    informe = await app_client.get(
        "/api/reports/cancellations", params=rango(DIA, DIA), headers=headers
    )
    assert informe.status_code == 200, informe.text
    assert informe.json()["total"] == 1


async def test_reprogramar_al_mismo_horario(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    managed = await make_managed(db_session, at(10, days=LUNES_DIA))
    appointment_id = managed.appointment.id

    response = await _accion(
        app_client, managed, action="reschedule", starts_at=at(10, days=LUNES_DIA).isoformat()
    )

    assert response.status_code == 200
    assert response.json()["appointment"]["starts_at"] == at(10, days=LUNES_DIA).isoformat()
    eventos = await _eventos(db_session, appointment_id)
    assert AppointmentEventType.RESCHEDULED not in eventos
    _replay_de(eventos, "reschedule")
