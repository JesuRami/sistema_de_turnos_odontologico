"""Reprogramar por token (C-08, D8): mismo turno, mismo profesional, grilla y EXCLUDE."""

from __future__ import annotations

from datetime import datetime, time, timedelta

import httpx
import pytest
from app.models import AppointmentEventType, AppointmentOrigin, AppointmentStatus
from sqlalchemy.ext.asyncio import AsyncSession

from tests.appointment_helpers import at, events_of, reload
from tests.booking_helpers import make_booking
from tests.conftest import AGENDA_NOW, MutableClock
from tests.factories import (
    make_appointment,
    make_chair,
    make_patient,
    make_professional,
    make_schedule_rule,
)
from tests.manage_helpers import Managed, make_managed, token_hash

pytestmark = pytest.mark.integration

LUNES_PROXIMO = 7


def _a(hh: int, mm: int = 0) -> datetime:
    return at(hh, mm, days=LUNES_PROXIMO)


async def _mover(client: httpx.AsyncClient, managed: Managed, destino: datetime) -> httpx.Response:
    return await client.patch(
        managed.url, json={"action": "reschedule", "starts_at": destino.isoformat()}
    )


async def test_reprogramacion_exitosa_conserva_turno_origen_y_token(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    managed = await make_managed(db_session, _a(10))
    appointment_id = managed.appointment.id

    response = await _mover(app_client, managed, _a(11))

    assert response.status_code == 200, response.text
    assert response.json()["appointment"]["starts_at"] == _a(11).isoformat()
    assert response.headers["Cache-Control"] == "no-store"
    turno = await reload(db_session, appointment_id)
    assert (turno.starts_at, turno.ends_at) == (_a(11), _a(11, 30))
    assert turno.origin is AppointmentOrigin.ONLINE
    assert turno.manage_token_hash == token_hash(managed.token)
    assert turno.status is AppointmentStatus.PENDING
    eventos = await events_of(db_session, appointment_id)
    assert [e.event for e in eventos] == [AppointmentEventType.RESCHEDULED]
    payload = eventos[0].payload
    assert datetime.fromisoformat(payload["before"]["starts_at"]) == _a(10)
    assert datetime.fromisoformat(payload["after"]["starts_at"]) == _a(11)
    assert payload["source"] == "manage_link"
    assert (await app_client.get(managed.url)).status_code == 200  # el link sigue sirviendo


async def test_reprogramacion_fuera_de_la_ventana(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    """Ventana de 24 h y turno en 3 h: se deriva a la clínica."""
    managed = await make_managed(db_session, AGENDA_NOW + timedelta(hours=3))
    inicio = managed.appointment.starts_at
    appointment_id = managed.appointment.id

    response = await _mover(app_client, managed, _a(11))

    assert response.status_code == 409
    assert response.json() == {"detail": "cancellation_window_closed"}
    assert (await reload(db_session, appointment_id)).starts_at == inicio


async def test_inicio_fuera_de_la_grilla(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    managed = await make_managed(db_session, _a(10))
    appointment_id = managed.appointment.id

    response = await _mover(app_client, managed, _a(9, 10))

    assert response.status_code == 422
    assert response.json() == {"detail": "slot_not_offered"}
    assert (await reload(db_session, appointment_id)).starts_at == _a(10)


async def test_inicio_en_el_pasado(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    managed = await make_managed(db_session, _a(10))

    response = await _mover(app_client, managed, AGENDA_NOW - timedelta(hours=1))

    assert response.status_code == 422
    assert response.json() == {"detail": "appointment_in_past"}


async def test_horario_ocupado_responde_alternativos_publicos(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    managed = await make_managed(db_session, _a(10))
    b = managed.booking
    otro = await make_patient(db_session, b.clinic)
    ocupante = await make_appointment(
        db_session,
        b.clinic,
        patient=otro,
        professional=b.professional,
        chair=b.chair,
        starts_at=_a(11),
    )
    appointment_id, chair_id = managed.appointment.id, b.chair.id

    response = await _mover(app_client, managed, _a(11))

    assert response.status_code == 409
    cuerpo = response.json()
    assert cuerpo["detail"] == "slot_taken"
    assert "conflicts" not in cuerpo
    assert 1 <= len(cuerpo["alternatives"]) <= 3
    for alternativo in cuerpo["alternatives"]:
        assert set(alternativo) == {"starts_at", "ends_at"}
    inicios = [datetime.fromisoformat(a["starts_at"]) for a in cuerpo["alternatives"]]
    assert inicios == sorted(inicios)
    assert _a(11) not in inicios
    for valor in (ocupante.id, chair_id, b.professional.id):
        assert str(valor) not in response.text
    turno = await reload(db_session, appointment_id)
    assert (turno.starts_at, turno.status, turno.chair_id) == (
        _a(10),
        AppointmentStatus.PENDING,
        chair_id,
    )


# ------------------------------------------------------- candidatos (8.3)


async def test_se_mueve_al_sillon_libre_cuando_otro_esta_ocupado(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    """Dos sillones con regla a la misma hora; el primero (por id) ocupado a las 11:00."""
    b = await make_booking(db_session)
    segundo = await make_chair(db_session, b.clinic, name="Sillón Ficticio Dos")
    await make_schedule_rule(db_session, b.clinic, b.professional, segundo, weekday=0)
    primero_id = min(b.chair.id, segundo.id)
    libre_id = max(b.chair.id, segundo.id)
    # El turno a mover está a las 10:00 en el sillón "libre"; a las 11:00 el otro está tomado
    # por un turno de otro profesional (ocupa el sillón, no al profesional).
    managed = await make_managed(db_session, _a(10), booking=b, chair_id=libre_id)
    colega = await make_professional(db_session, b.clinic, display_name="Dra. Colega Ficticia")
    await make_appointment(
        db_session,
        b.clinic,
        patient=await make_patient(db_session, b.clinic),
        professional=colega,
        chair=segundo if segundo.id == primero_id else b.chair,
        starts_at=_a(11),
    )
    appointment_id = managed.appointment.id

    response = await _mover(app_client, managed, _a(11))

    assert response.status_code == 200, response.text
    turno = await reload(db_session, appointment_id)
    assert (turno.starts_at, turno.chair_id) == (_a(11), libre_id)


async def test_el_turno_no_se_sale_de_la_franja(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    """Un turno de 60 min no se mueve a las 12:30 si la franja termina a las 13:00."""
    b = await make_booking(db_session, end_time=time(13, 0))
    managed = await make_managed(db_session, _a(10), booking=b, minutes=60)
    appointment_id = managed.appointment.id

    response = await _mover(app_client, managed, _a(12, 30))

    assert response.status_code == 422
    assert response.json() == {"detail": "slot_not_offered"}
    assert (await reload(db_session, appointment_id)).starts_at == _a(10)
