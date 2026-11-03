"""`POST /api/appointments/{id}/transitions` (C-05 tareas 6.2/6.3, RN-ST-03/04, RN-CX-02..05)."""

from __future__ import annotations

import uuid

import httpx
import pytest
from app.core.settings import Settings
from app.models import (
    AppointmentEventType,
    AppointmentOrigin,
    AppointmentStatus,
    CancellationReason,
)
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tests.appointment_helpers import Agenda, at, events_of, make_agenda, post, reload, seed
from tests.conftest import MutableClock
from tests.factories import make_professional

pytestmark = pytest.mark.integration


async def _transicion(
    client: httpx.AsyncClient,
    agenda: Agenda,
    appointment_id: uuid.UUID,
    rol: str = "recepcion",
    /,
    **body: object,
) -> httpx.Response:
    return await client.post(
        f"/api/appointments/{appointment_id}/transitions", json=body, headers=agenda.headers[rol]
    )


async def test_recepcion_confirma_un_pendiente(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await seed(
        db_session,
        agenda,
        at(10),
        origin=AppointmentOrigin.ONLINE,
        status=AppointmentStatus.PENDING,
        created_by_user_id=None,
    )

    response = await _transicion(app_client, agenda, turno.id, to="confirmed")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "confirmed"
    eventos = await events_of(db_session, turno.id)
    assert [(e.event, e.from_status, e.to_status) for e in eventos] == [
        (AppointmentEventType.CONFIRMED, AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED)
    ]


async def test_desde_estado_terminal_es_409_y_no_cambia(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await seed(
        db_session,
        agenda,
        at(10),
        status=AppointmentStatus.CANCELLED,
        cancelled_at=at(7),
        cancellation_reason=CancellationReason.PACIENTE,
    )

    response = await _transicion(app_client, agenda, turno.id, to="confirmed")

    assert response.status_code == 409
    assert response.json()["detail"] == "invalid_transition"
    assert (await reload(db_session, turno.id)).status == AppointmentStatus.CANCELLED
    assert await events_of(db_session, turno.id) == []


async def test_pendiente_no_pasa_directo_a_presente(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await seed(db_session, agenda, at(10), status=AppointmentStatus.PENDING)
    response = await _transicion(app_client, agenda, turno.id, to="present")
    assert response.json()["detail"] == "invalid_transition"


# --------------------------------------------------------------- asistencia


async def test_presente_en_un_turno_de_manana_es_409(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await seed(db_session, agenda, at(10, days=1))
    response = await _transicion(app_client, agenda, turno.id, to="present")
    assert response.status_code == 409
    assert response.json()["detail"] == "attendance_too_early"


async def test_no_show_antes_de_la_hora_es_409(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await seed(db_session, agenda, at(10))
    response = await _transicion(app_client, agenda, turno.id, to="no_show")
    assert response.json()["detail"] == "attendance_too_early"


@pytest.mark.parametrize("destino", ["absent", "no_show"])
async def test_ausencia_desde_la_hora_libera_el_hueco(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
    destino: str,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await seed(db_session, agenda, at(10))
    agenda_clock.current = at(10, 5)

    response = await _transicion(app_client, agenda, turno.id, to=destino)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == destino
    # El hueco queda libre: se puede registrar otro paciente que llegó (mismo día).
    assert (await post(app_client, agenda, at(10))).status_code == 201


async def test_odontologo_marca_presente_su_turno_de_hoy(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await seed(db_session, agenda, at(10))

    response = await _transicion(app_client, agenda, turno.id, "odontologo", to="present")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "present"
    assert "phone_e164" not in response.json()["patient"]


async def test_odontologo_no_toca_turnos_ajenos(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    colega = await make_professional(db_session, agenda.staff.clinic, display_name="Dra. Colega")
    ajeno = await seed(db_session, agenda, at(10), professional=colega)

    response = await _transicion(app_client, agenda, ajeno.id, "odontologo", to="present")

    assert response.status_code == 404
    assert response.json()["detail"] == "not_found"


@pytest.mark.parametrize(
    "body", [{"to": "confirmed"}, {"to": "cancelled", "reason": "profesional"}]
)
async def test_odontologo_no_confirma_ni_cancela(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
    body: dict[str, object],
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await seed(db_session, agenda, at(10), status=AppointmentStatus.PENDING)
    response = await _transicion(app_client, agenda, turno.id, "odontologo", **body)
    assert response.status_code == 403
    assert response.json()["detail"] == "forbidden_role"


# ------------------------------------------------------------- cancelación


@pytest.mark.parametrize(
    "body",
    [
        {"to": "cancelled"},
        {"to": "cancelled", "reason": "aburrimiento"},
        {"to": "cancelled", "reason": "otro", "note": "x" * 501},
        {"to": "present", "reason": "otro"},
        {"to": "borrado"},
        {"to": "cancelled", "reason": "otro", "clinic_id": str(uuid.uuid4())},
    ],
)
async def test_cancelacion_invalida_es_422_y_no_cambia(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
    body: dict[str, object],
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await seed(db_session, agenda, at(10, days=7))
    response = await _transicion(app_client, agenda, turno.id, **body)
    assert response.status_code == 422
    assert (await reload(db_session, turno.id)).status == AppointmentStatus.CONFIRMED


async def test_cancelacion_con_tiempo_no_es_tardia_y_libera_el_hueco(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await seed(db_session, agenda, at(10, days=7))

    response = await _transicion(
        app_client, agenda, turno.id, to="cancelled", reason="paciente", note="Avisó por teléfono"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["cancellation_reason"] == "paciente"
    assert body["cancellation_note"] == "Avisó por teléfono"
    assert body["cancelled_at"] is not None
    evento = (await events_of(db_session, turno.id))[0]
    assert evento.event == AppointmentEventType.CANCELLED
    assert evento.payload["late"] is False
    assert evento.payload["reason"] == "paciente"
    assert (await post(app_client, agenda, at(10, days=7))).status_code == 201


async def test_cancelacion_tardia_queda_registrada(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    assert agenda.staff.clinic.cancellation_window_hours == 24
    turno = await seed(db_session, agenda, at(11))  # empieza en 3 h

    response = await _transicion(
        app_client, agenda, turno.id, "admin", to="cancelled", reason="otro"
    )

    assert response.status_code == 200
    assert (await events_of(db_session, turno.id))[0].payload["late"] is True


async def test_turno_ya_empezado_no_se_cancela(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await seed(db_session, agenda, at(10))
    agenda_clock.current = at(10, 1)

    response = await _transicion(app_client, agenda, turno.id, to="cancelled", reason="paciente")

    assert response.status_code == 409
    assert response.json()["detail"] == "appointment_started"


async def test_turno_presente_no_se_cancela(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await seed(db_session, agenda, at(10), status=AppointmentStatus.PRESENT)
    response = await _transicion(app_client, agenda, turno.id, to="cancelled", reason="paciente")
    assert response.status_code == 409
    assert response.json()["detail"] == "invalid_transition"
