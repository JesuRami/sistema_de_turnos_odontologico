"""Sobreturnos explícitos, con motivo y tope diario (C-05 grupo 5, RN-SB-01..03)."""

from __future__ import annotations

import uuid

import httpx
import pytest
from app.core.settings import Settings
from app.models import AppointmentEventType, AppointmentStatus, CancellationReason
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tests.appointment_helpers import at, events_of, make_agenda, post, seed
from tests.conftest import MutableClock

pytestmark = pytest.mark.integration

MOTIVO = "Urgencia ficticia de dolor"


async def test_sobreturno_sin_motivo_es_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    await seed(db_session, agenda, at(10))
    for extra in ({}, {"overbooking_reason": "   "}):
        response = await post(app_client, agenda, at(10), is_overbooking=True, **extra)
        assert response.status_code == 422


async def test_sobreturno_valido_registra_colisiones(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    existente = await seed(db_session, agenda, at(10))

    response = await post(
        app_client, agenda, at(10), is_overbooking=True, overbooking_reason=MOTIVO
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["is_overbooking"] is True
    assert body["overbooking_reason"] == MOTIVO
    eventos = await events_of(db_session, uuid.UUID(body["id"]))
    assert [e.event for e in eventos] == [AppointmentEventType.OVERBOOKING_CREATED]
    assert eventos[0].payload["conflicts"] == [str(existente.id)]
    assert eventos[0].payload["reason"] == MOTIVO
    assert eventos[0].payload["over_limit"] is False
    assert eventos[0].actor_user_id is not None


async def test_sobreturno_innecesario_es_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    response = await post(
        app_client, agenda, at(10), is_overbooking=True, overbooking_reason=MOTIVO
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "overbooking_not_needed"


async def test_sobreturno_no_exime_de_horario_ni_bloqueos(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    response = await post(
        app_client, agenda, at(13, 30), is_overbooking=True, overbooking_reason=MOTIVO
    )
    assert response.json()["detail"] == "outside_schedule"


async def test_turno_normal_no_se_superpone_a_un_sobreturno_vigente(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    original = await seed(db_session, agenda, at(10))
    sobreturno = await seed(
        db_session, agenda, at(10), is_overbooking=True, overbooking_reason=MOTIVO
    )
    original.status = AppointmentStatus.CANCELLED
    original.cancelled_at = at(7)
    original.cancellation_reason = CancellationReason.PACIENTE
    await db_session.flush()

    response = await post(app_client, agenda, at(10))

    assert response.status_code == 409
    assert response.json()["detail"] == "slot_taken"
    assert response.json()["conflicts"] == [str(sobreturno.id)]


async def test_odontologo_no_crea_sobreturnos(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    await seed(db_session, agenda, at(10))
    response = await post(
        app_client, agenda, at(10), "odontologo", is_overbooking=True, overbooking_reason=MOTIVO
    )
    assert response.status_code == 403


async def test_recepcion_no_supera_el_tope_diario(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    assert agenda.staff.clinic.max_overbookings_per_day == 2
    for hora in (9, 10, 11):
        await seed(db_session, agenda, at(hora))
    for hora in (9, 10):
        await seed(db_session, agenda, at(hora), is_overbooking=True, overbooking_reason=MOTIVO)

    response = await post(
        app_client, agenda, at(11), is_overbooking=True, overbooking_reason=MOTIVO
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "overbooking_limit"


async def test_sobreturnos_de_otro_dia_o_cancelados_no_cuentan(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    for hora in (9, 10, 11):
        await seed(db_session, agenda, at(hora))
    await seed(db_session, agenda, at(9, days=7), is_overbooking=True, overbooking_reason=MOTIVO)
    await seed(
        db_session,
        agenda,
        at(9),
        is_overbooking=True,
        overbooking_reason=MOTIVO,
        status=AppointmentStatus.CANCELLED,
        cancelled_at=at(7),
        cancellation_reason=CancellationReason.CLINICA,
    )
    await seed(db_session, agenda, at(10), is_overbooking=True, overbooking_reason=MOTIVO)

    response = await post(
        app_client, agenda, at(11), is_overbooking=True, overbooking_reason=MOTIVO
    )

    assert response.status_code == 201, response.text


async def test_admin_supera_el_tope_y_queda_registrado(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    for hora in (9, 10, 11):
        await seed(db_session, agenda, at(hora))
    for hora in (9, 10):
        await seed(db_session, agenda, at(hora), is_overbooking=True, overbooking_reason=MOTIVO)

    response = await post(
        app_client, agenda, at(11), "admin", is_overbooking=True, overbooking_reason=MOTIVO
    )

    assert response.status_code == 201, response.text
    eventos = await events_of(db_session, uuid.UUID(response.json()["id"]))
    assert eventos[0].payload["over_limit"] is True
