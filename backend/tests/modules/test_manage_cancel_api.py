"""Cancelar por token (C-08, D7): ventana de la clínica, motivo de lista cerrada, nota acotada."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import httpx
import pytest
from app.core.settings import Settings
from app.models import AppointmentEventType, AppointmentStatus, CancellationReason, UserRole
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tests.appointment_helpers import at, events_of, reload
from tests.auth_helpers import issue_session
from tests.conftest import AGENDA_NOW, MutableClock
from tests.factories import make_user, unique_email
from tests.manage_helpers import Managed, make_managed

pytestmark = pytest.mark.integration


async def _cancelar(client: httpx.AsyncClient, managed: Managed, **body: Any) -> httpx.Response:
    return await client.patch(managed.url, json={"action": "cancel", **body})


async def _evento_cancelado(db_session: AsyncSession, managed: Managed | uuid.UUID) -> Any:
    appointment_id = managed if isinstance(managed, uuid.UUID) else managed.appointment.id
    eventos = [
        e
        for e in await events_of(db_session, appointment_id)
        if e.event is AppointmentEventType.CANCELLED
    ]
    assert len(eventos) == 1
    return eventos[0]


async def test_cancelacion_en_plazo_con_motivo(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    managed = await make_managed(db_session, at(10, days=5), status=AppointmentStatus.CONFIRMED)

    response = await _cancelar(app_client, managed, reason="viaje")

    assert response.status_code == 200, response.text
    assert response.json()["appointment"]["status"] == "cancelled"
    turno = await reload(db_session, managed.appointment.id)
    assert turno.cancellation_reason is CancellationReason.PACIENTE
    assert turno.cancellation_note is None
    payload = (await _evento_cancelado(db_session, managed)).payload
    assert payload["reason"] == "paciente"
    assert payload["late"] is False
    assert payload["patient_reason"] == "viaje"
    assert payload["source"] == "manage_link"


async def test_cancelacion_sin_motivo(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    managed = await make_managed(db_session, at(10, days=5))

    response = await _cancelar(app_client, managed)

    assert response.status_code == 200
    payload = (await _evento_cancelado(db_session, managed)).payload
    assert payload["reason"] == "paciente"
    assert "patient_reason" not in payload


async def test_la_nota_solo_se_guarda_con_otro_y_nunca_en_el_evento(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    con_otro = await make_managed(db_session, at(10, days=5))
    con_viaje = await make_managed(db_session, at(11, days=5), booking=con_otro.booking)

    ids = (con_otro.appointment.id, con_viaje.appointment.id)

    await _cancelar(app_client, con_otro, reason="otro", note="Se me rompió el auto ficticio")
    await _cancelar(app_client, con_viaje, reason="viaje", note="Texto que no se guarda")

    assert (await reload(db_session, ids[0])).cancellation_note == "Se me rompió el auto ficticio"
    assert (await reload(db_session, ids[1])).cancellation_note is None
    for appointment_id in ids:
        payload = (await _evento_cancelado(db_session, appointment_id)).payload
        assert "note" not in payload
        assert "auto ficticio" not in str(payload)


@pytest.mark.parametrize(
    "cuerpo",
    [{"reason": "otro", "note": "x" * 201}, {"reason": "motivo_inventado"}, {"extra": 1}],
    ids=["nota_larga", "motivo_fuera_de_catalogo", "campo_extra"],
)
async def test_cuerpo_invalido_es_422_y_el_turno_no_cambia(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    agenda_clock: MutableClock,
    cuerpo: dict[str, Any],
) -> None:
    managed = await make_managed(db_session, at(10, days=5))

    response = await _cancelar(app_client, managed, **cuerpo)

    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_request"
    assert (await reload(db_session, managed.appointment.id)).status is AppointmentStatus.PENDING


async def test_cancelar_un_turno_presente(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    managed = await make_managed(
        db_session, AGENDA_NOW - timedelta(minutes=10), status=AppointmentStatus.PRESENT
    )

    response = await _cancelar(app_client, managed)

    assert response.status_code == 409
    assert response.json() == {"detail": "invalid_transition"}
    assert (await reload(db_session, managed.appointment.id)).status is AppointmentStatus.PRESENT


async def test_cancelar_un_turno_de_ayer(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    managed = await make_managed(
        db_session, AGENDA_NOW - timedelta(days=1), status=AppointmentStatus.CONFIRMED
    )

    response = await _cancelar(app_client, managed)

    assert response.status_code == 422
    assert response.json() == {"detail": "appointment_in_past"}
    assert (await reload(db_session, managed.appointment.id)).status is AppointmentStatus.CONFIRMED


async def test_cancelacion_tardia_se_deriva_a_la_clinica(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    """Ventana de 24 h y turno en 3 h: `409 cancellation_window_closed` sin mutar."""
    managed = await make_managed(db_session, AGENDA_NOW + timedelta(hours=3))

    response = await _cancelar(app_client, managed, reason="enfermedad")

    assert response.status_code == 409
    assert response.json() == {"detail": "cancellation_window_closed"}
    assert (await reload(db_session, managed.appointment.id)).status is AppointmentStatus.PENDING
    assert await events_of(db_session, managed.appointment.id) == []


async def test_cancelar_libera_el_hueco_para_otros_y_en_la_agenda_de_recepcion(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    """El 10:00 cancelado por token se ofrece en el link de otro turno y figura en recepción."""
    cancelado = await make_managed(db_session, at(10, days=7))
    otro = await make_managed(db_session, at(11, days=7), booking=cancelado.booking)
    recepcion = await make_user(
        db_session,
        cancelado.booking.clinic,
        email=unique_email("recepcion.ficticia"),
        role=UserRole.RECEPCION,
        must_change_password=False,
    )
    headers = (await issue_session(redis_client, settings, recepcion)).headers
    rango = {"from": at(0, days=7).isoformat(), "to": at(0, days=8).isoformat()}

    antes = await app_client.get(f"{otro.url}/availability", params=rango)
    assert at(10, days=7).isoformat() not in [s["starts_at"] for s in antes.json()["slots"]]

    assert (await _cancelar(app_client, cancelado, reason="viaje")).status_code == 200

    despues = await app_client.get(f"{otro.url}/availability", params=rango)
    assert at(10, days=7).isoformat() in [s["starts_at"] for s in despues.json()["slots"]]
    agenda = await app_client.get("/api/appointments", params=rango, headers=headers)
    assert agenda.status_code == 200, agenda.text
    estados = {i["id"]: i["status"] for i in agenda.json()["items"]}
    assert estados[str(cancelado.appointment.id)] == "cancelled"
    assert estados[str(otro.appointment.id)] == "pending"
