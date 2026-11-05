"""Huecos para reprogramar por token (C-08, D8): mismo profesional, misma definición que C-07."""

from __future__ import annotations

from datetime import datetime, time, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.appointment_helpers import at
from tests.booking_helpers import make_booking
from tests.conftest import AGENDA_NOW, MutableClock
from tests.factories import (
    make_appointment,
    make_patient,
    make_professional,
    make_schedule_rule,
)
from tests.manage_helpers import Managed, make_managed

pytestmark = pytest.mark.integration

PROXIMO_LUNES = 7


async def _huecos(
    client: httpx.AsyncClient,
    managed: Managed,
    desde: datetime | None = None,
    hasta: datetime | None = None,
) -> httpx.Response:
    return await client.get(
        f"{managed.url}/availability",
        params={
            "from": (desde or at(0, days=PROXIMO_LUNES)).isoformat(),
            "to": (hasta or at(0, days=PROXIMO_LUNES + 1)).isoformat(),
        },
    )


def _inicios(response: httpx.Response) -> list[datetime]:
    return [datetime.fromisoformat(s["starts_at"]) for s in response.json()["slots"]]


async def test_huecos_del_mismo_profesional_sin_el_ocupado_y_con_el_propio(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    """Otro turno a las 10:00 no se ofrece; el horario actual del turno (15:00) sí."""
    b = await make_booking(db_session, end_time=time(17, 0))
    managed = await make_managed(db_session, at(15, days=PROXIMO_LUNES), booking=b)
    otro_paciente = await make_patient(db_session, b.clinic)
    await make_appointment(
        db_session,
        b.clinic,
        patient=otro_paciente,
        professional=b.professional,
        chair=b.chair,
        starts_at=at(10, days=PROXIMO_LUNES),
    )

    response = await _huecos(app_client, managed)

    assert response.status_code == 200, response.text
    inicios = _inicios(response)
    assert at(10, days=PROXIMO_LUNES) not in inicios
    assert at(15, days=PROXIMO_LUNES) in inicios
    assert at(9, days=PROXIMO_LUNES) in inicios
    assert response.json()["timezone"] == "America/Argentina/Buenos_Aires"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"


async def test_huecos_de_otro_profesional_no_se_ofrecen(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    """Un colega con agenda libre el martes no agrega huecos al turno de este profesional."""
    b = await make_booking(db_session)
    managed = await make_managed(db_session, at(10, days=PROXIMO_LUNES), booking=b)
    colega = await make_professional(db_session, b.clinic, display_name="Dra. Colega Ficticia")
    await make_schedule_rule(db_session, b.clinic, colega, b.chair, weekday=1)

    martes = await _huecos(
        app_client,
        managed,
        at(0, days=PROXIMO_LUNES + 1),
        at(0, days=PROXIMO_LUNES + 2),
    )

    assert martes.status_code == 200
    assert martes.json()["slots"] == []


async def test_la_respuesta_no_trae_ids(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    managed = await make_managed(db_session, at(10, days=PROXIMO_LUNES))

    response = await _huecos(app_client, managed)

    for slot in response.json()["slots"]:
        assert set(slot) == {"starts_at", "ends_at"}
    for valor in (
        managed.booking.professional.id,
        managed.booking.chair.id,
        managed.appointment.id,
        managed.patient.id,
    ):
        assert str(valor) not in response.text


@pytest.mark.parametrize(
    ("desde", "hasta"),
    [
        (at(0, days=PROXIMO_LUNES), at(0, days=PROXIMO_LUNES + 30)),
        (at(0, days=PROXIMO_LUNES), at(0, days=PROXIMO_LUNES)),
        (at(0, days=PROXIMO_LUNES + 1), at(0, days=PROXIMO_LUNES)),
        (at(0, days=70), at(0, days=71)),
    ],
    ids=["mas_de_14_dias", "vacio", "invertido", "fuera_del_horizonte"],
)
async def test_rango_invalido(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    agenda_clock: MutableClock,
    desde: datetime,
    hasta: datetime,
) -> None:
    managed = await make_managed(db_session, at(10, days=PROXIMO_LUNES))

    response = await _huecos(app_client, managed, desde, hasta)

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_range"}


async def test_token_vencido_en_disponibilidad(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    from app.models import AppointmentStatus

    managed = await make_managed(
        db_session, AGENDA_NOW - timedelta(days=5), status=AppointmentStatus.CONFIRMED
    )

    response = await _huecos(app_client, managed)

    assert response.status_code == 410
    assert response.json()["detail"] == "manage_link_expired"
