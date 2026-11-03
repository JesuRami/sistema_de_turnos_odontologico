"""`PATCH /api/appointments/{id}`: reprogramación atómica y notas (C-05 grupo 7, RN-AG-06)."""

from __future__ import annotations

import uuid
from datetime import datetime, time

import httpx
import pytest
from app.core.settings import Settings
from app.models import AppointmentEventType, AppointmentStatus, CancellationReason
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tests.appointment_helpers import Agenda, at, events_of, iso, make_agenda, reload, seed
from tests.conftest import MutableClock
from tests.factories import make_chair, make_professional, make_schedule_rule

pytestmark = pytest.mark.integration


async def _patch(
    client: httpx.AsyncClient,
    agenda: Agenda,
    appointment_id: uuid.UUID,
    rol: str = "recepcion",
    /,
    **body: object,
) -> httpx.Response:
    return await client.patch(
        f"/api/appointments/{appointment_id}", json=body, headers=agenda.headers[rol]
    )


def _instante(valor: str) -> datetime:
    return datetime.fromisoformat(valor)


async def test_reprogramacion_exitosa_conserva_el_id_y_audita(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await seed(db_session, agenda, at(10))

    response = await _patch(app_client, agenda, turno.id, starts_at=iso(11))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(turno.id)
    assert _instante(body["starts_at"]) == at(11)
    assert _instante(body["ends_at"]) == at(11, 30)
    eventos = await events_of(db_session, turno.id)
    assert [e.event for e in eventos] == [AppointmentEventType.RESCHEDULED]
    payload = eventos[0].payload
    assert _instante(payload["before"]["starts_at"]) == at(10)
    assert _instante(payload["after"]["starts_at"]) == at(11)
    assert set(payload["before"]) == {"starts_at", "ends_at", "occupied_until"}


async def test_reprogramar_sobre_si_mismo_no_colisiona(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await seed(db_session, agenda, at(10))
    response = await _patch(app_client, agenda, turno.id, starts_at=iso(10, 15))
    assert response.status_code == 200, response.text


async def test_cambio_de_profesional_recalcula_el_buffer(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    colega = await make_professional(
        db_session, agenda.staff.clinic, display_name="Dra. Buffer", buffer_min=15
    )
    otro_sillon = await make_chair(db_session, agenda.staff.clinic, name="Sillón Ficticio B")
    await make_schedule_rule(
        db_session, agenda.staff.clinic, colega, otro_sillon, start_time=time(9), end_time=time(13)
    )
    turno = await seed(db_session, agenda, at(10))

    response = await _patch(
        app_client,
        agenda,
        turno.id,
        professional_id=str(colega.id),
        chair_id=str(otro_sillon.id),
        duration_min=45,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["professional_id"] == str(colega.id)
    assert _instante(body["ends_at"]) == at(10, 45)
    assert _instante(body["occupied_until"]) == at(11)


async def test_reprogramacion_que_colisiona_deja_el_turno_intacto(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await seed(db_session, agenda, at(10))
    ocupante = await seed(db_session, agenda, at(11))

    response = await _patch(app_client, agenda, turno.id, starts_at=iso(11))

    assert response.status_code == 409
    assert response.json()["detail"] == "slot_taken"
    assert response.json()["conflicts"] == [str(ocupante.id)]
    releido = await reload(db_session, turno.id)
    assert releido.starts_at == at(10)
    assert releido.status == AppointmentStatus.CONFIRMED
    assert await events_of(db_session, turno.id) == []


@pytest.mark.parametrize(
    ("cambio", "codigo"),
    [
        ({"starts_at": iso(13, 30)}, "outside_schedule"),
        ({"starts_at": iso(10, days=-7)}, "appointment_in_past"),
        ({"is_overbooking": True, "overbooking_reason": "Sin colisión"}, "overbooking_not_needed"),
    ],
)
async def test_reprogramacion_revalida_las_condiciones_de_alta(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
    cambio: dict[str, object],
    codigo: str,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await seed(db_session, agenda, at(10))
    response = await _patch(app_client, agenda, turno.id, **cambio)
    assert response.status_code == 422
    assert response.json()["detail"] == codigo
    assert (await reload(db_session, turno.id)).starts_at == at(10)


async def test_recurso_destino_inactivo_es_409(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    inactivo = await make_chair(db_session, agenda.staff.clinic, name="Sillón Baja", active=False)
    turno = await seed(db_session, agenda, at(10))
    response = await _patch(app_client, agenda, turno.id, chair_id=str(inactivo.id))
    assert response.status_code == 409
    assert response.json()["detail"] == "resource_inactive"


async def test_turno_empezado_o_terminal_no_se_reprograma(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    empezado = await seed(db_session, agenda, at(9))
    cancelado = await seed(
        db_session,
        agenda,
        at(10),
        status=AppointmentStatus.CANCELLED,
        cancelled_at=at(7),
        cancellation_reason=CancellationReason.PACIENTE,
    )
    agenda_clock.current = at(9, 10)

    r_empezado = await _patch(app_client, agenda, empezado.id, starts_at=iso(12))
    r_cancelado = await _patch(app_client, agenda, cancelado.id, starts_at=iso(12))

    assert (r_empezado.status_code, r_empezado.json()["detail"]) == (409, "appointment_started")
    assert (r_cancelado.status_code, r_cancelado.json()["detail"]) == (409, "invalid_transition")


async def test_editar_notas_emite_updated(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await seed(db_session, agenda, at(10))

    response = await _patch(app_client, agenda, turno.id, notes="Trae estudios ficticios")
    repetido = await _patch(app_client, agenda, turno.id, notes="Trae estudios ficticios")

    assert response.status_code == 200
    assert response.json()["notes"] == "Trae estudios ficticios"
    assert repetido.status_code == 200
    eventos = await events_of(db_session, turno.id)
    assert [e.event for e in eventos] == [AppointmentEventType.UPDATED]
    assert eventos[0].payload == {"notes": [None, "Trae estudios ficticios"]}


@pytest.mark.parametrize(
    "body",
    [
        {"starts_at": None},
        {"starts_at": "2030-01-07T11:00:00"},
        {"status": "cancelled"},
        {"patient_id": str(uuid.uuid4())},
        {"clinic_id": str(uuid.uuid4())},
    ],
)
async def test_patch_invalido_es_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
    body: dict[str, object],
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await seed(db_session, agenda, at(10))
    response = await _patch(app_client, agenda, turno.id, **body)
    assert response.status_code == 422


async def test_odontologo_no_reprograma(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await seed(db_session, agenda, at(10))
    response = await _patch(app_client, agenda, turno.id, "odontologo", starts_at=iso(11))
    assert response.status_code == 403


async def test_delete_no_existe(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await seed(db_session, agenda, at(10))

    response = await app_client.delete(
        f"/api/appointments/{turno.id}", headers=agenda.headers["admin"]
    )

    assert response.status_code == 405
    assert (await reload(db_session, turno.id)).status == AppointmentStatus.CONFIRMED
