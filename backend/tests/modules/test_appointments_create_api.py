"""Alta de turno desde recepción (C-05 tareas 4.2/4.3, US-011, RN-AG-01/04/06, regla dura 1)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta

import httpx
import pytest
from app.core.settings import Settings
from app.models import (
    ActorType,
    AppointmentEventType,
    AppointmentStatus,
    CancellationReason,
)
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tests.appointment_helpers import (
    PACIENTE_NOMBRE,
    at,
    events_of,
    make_agenda,
    post,
    seed,
)
from tests.conftest import MutableClock
from tests.factories import (
    make_block,
    make_chair,
    make_clinic,
    make_patient,
    make_professional,
    make_schedule_rule,
)

pytestmark = pytest.mark.integration


def _instante(valor: str) -> datetime:
    return datetime.fromisoformat(valor)


# --------------------------------------------------------------------- alta


async def test_recepcion_crea_turno_con_duracion_de_la_regla(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)

    response = await post(app_client, agenda, at(10))

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "confirmed"
    assert body["origin"] == "reception"
    assert body["is_overbooking"] is False
    assert _instante(body["starts_at"]) == at(10)
    assert _instante(body["ends_at"]) == at(10, 30)
    assert _instante(body["occupied_until"]) == at(10, 30)
    assert body["patient"] == {
        "id": str(agenda.patient.id),
        "full_name": PACIENTE_NOMBRE,
        "phone_e164": agenda.patient.phone_e164,
        "email": None,
    }
    eventos = await events_of(db_session, uuid.UUID(body["id"]))
    assert [e.event for e in eventos] == [AppointmentEventType.CREATED]
    assert eventos[0].actor_type == ActorType.USER
    assert eventos[0].to_status == AppointmentStatus.CONFIRMED
    assert eventos[0].from_status is None
    assert PACIENTE_NOMBRE not in str(eventos[0].payload)


async def test_admin_indica_duracion_y_el_buffer_extiende_lo_ocupado(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    agenda.staff.professional.buffer_min = 10
    await db_session.flush()

    response = await post(app_client, agenda, at(12), "admin", duration_min=45, notes="Control")

    assert response.status_code == 201, response.text
    body = response.json()
    assert _instante(body["ends_at"]) == at(12, 45)
    assert _instante(body["occupied_until"]) == at(12, 55)
    assert body["notes"] == "Control"


async def test_turno_de_hoy_ya_empezado_se_puede_registrar(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    agenda_clock.current = at(11)

    response = await post(app_client, agenda, at(9, 30))

    assert response.status_code == 201, response.text


async def test_odontologo_no_crea_turnos(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    response = await post(app_client, agenda, at(10), "odontologo")
    assert response.status_code == 403
    assert response.json()["detail"] == "forbidden_role"


@pytest.mark.parametrize("ajeno", ["patient_id", "professional_id", "chair_id"])
async def test_referencias_de_otra_clinica_son_422_sin_revelar(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
    ajeno: str,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    otra = await make_clinic(db_session)
    ajenos = {
        "patient_id": (await make_patient(db_session, otra)).id,
        "professional_id": (await make_professional(db_session, otra)).id,
        "chair_id": (await make_chair(db_session, otra)).id,
    }
    inexistente = await post(app_client, agenda, at(10), **{ajeno: str(uuid.uuid4())})
    de_otra = await post(app_client, agenda, at(10), **{ajeno: str(ajenos[ajeno])})

    assert de_otra.status_code == 422
    assert de_otra.json() == inexistente.json()


async def test_paciente_archivado_es_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    agenda.patient.archived_at = at(0, days=-30)
    await db_session.flush()
    response = await post(app_client, agenda, at(10))
    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_patient"


@pytest.mark.parametrize("recurso", ["professional", "chair"])
async def test_recurso_inactivo_es_409(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
    recurso: str,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    getattr(agenda.staff, recurso).active = False
    await db_session.flush()

    response = await post(app_client, agenda, at(10))

    assert response.status_code == 409
    assert response.json()["detail"] == "resource_inactive"


# ------------------------------------------------- horario, bloqueos, pasado


@pytest.mark.parametrize(
    ("inicio", "extra"),
    [
        (at(13, 30), {}),
        (at(8, 30), {}),
        (at(12, 45), {}),
        (at(12, 30), {"duration_min": 45}),
        (at(10, days=1), {}),
    ],
)
async def test_fuera_de_la_plantilla_es_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
    inicio: datetime,
    extra: dict[str, object],
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    response = await post(app_client, agenda, inicio, **extra)
    assert response.status_code == 422
    assert response.json()["detail"] == "outside_schedule"


@pytest.mark.parametrize(
    "regla", [{"active": False}, {"valid_to": date(2029, 12, 31)}, {"valid_from": date(2030, 2, 1)}]
)
async def test_regla_inactiva_o_no_vigente_es_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
    regla: dict[str, object],
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings, **regla)
    response = await post(app_client, agenda, at(10))
    assert response.status_code == 422
    assert response.json()["detail"] == "outside_schedule"


async def test_regla_de_otro_sillon_no_habilita(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    otro_sillon = await make_chair(db_session, agenda.staff.clinic, name="Sillón Ficticio Tres")
    response = await post(app_client, agenda, at(10), chair_id=str(otro_sillon.id))
    assert response.status_code == 422
    assert response.json()["detail"] == "outside_schedule"


@pytest.mark.parametrize("objetivo", ["professional", "chair"])
async def test_dentro_de_un_bloqueo_es_409(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
    objetivo: str,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    bloqueo = await make_block(
        db_session,
        agenda.staff.clinic,
        **{objetivo: getattr(agenda.staff, objetivo)},
        created_by_user_id=agenda.staff.admin.id,
        starts_at=at(10, 15),
        ends_at=at(11),
    )

    response = await post(app_client, agenda, at(10))

    assert response.status_code == 409
    assert response.json() == {"detail": "slot_blocked", "blocks": [str(bloqueo.id)]}


async def test_bloqueo_retirado_no_cuenta(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    await make_block(
        db_session,
        agenda.staff.clinic,
        professional=agenda.staff.professional,
        created_by_user_id=agenda.staff.admin.id,
        starts_at=at(9),
        ends_at=at(13),
        removed_at=at(7),
        removed_by_user_id=agenda.staff.admin.id,
    )
    response = await post(app_client, agenda, at(10))
    assert response.status_code == 201


async def test_turno_en_un_dia_pasado_es_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    response = await post(app_client, agenda, at(10, days=-7))
    assert response.status_code == 422
    assert response.json()["detail"] == "appointment_in_past"


@pytest.mark.parametrize(
    "invalido",
    [
        {"starts_at": "2030-01-07T10:00:00"},
        {"duration_min": 4},
        {"duration_min": 481},
        {"notes": "x" * 501},
        {"clinic_id": str(uuid.uuid4())},
        {"status": "pending"},
        {"origin": "online"},
        {"occupied_until": "2030-01-07T14:00:00+00:00"},
        {"overbooking_reason": "Sin marcar sobreturno"},
    ],
)
async def test_body_invalido_es_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
    invalido: dict[str, object],
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    valores = dict(invalido)
    inicio = valores.pop("starts_at", at(10))
    assert isinstance(inicio, str | datetime)
    response = await post(app_client, agenda, inicio, **valores)
    assert response.status_code == 422


# ---------------------------------------------------------------- colisiones


async def test_mismo_profesional_en_otro_sillon_es_409_slot_taken(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    otro_sillon = await make_chair(db_session, agenda.staff.clinic, name="Sillón Ficticio Dos")
    await make_schedule_rule(
        db_session,
        agenda.staff.clinic,
        agenda.staff.professional,
        otro_sillon,
        weekday=0,
        start_time=time(9),
        end_time=time(13),
        slot_duration_min=30,
    )
    existente = await seed(db_session, agenda, at(10))

    response = await post(app_client, agenda, at(10, 15), chair_id=str(otro_sillon.id))

    assert response.status_code == 409
    body = response.json()
    assert body["detail"] == "slot_taken"
    assert body["conflicts"] == [str(existente.id)]
    assert PACIENTE_NOMBRE not in response.text
    assert str(agenda.patient.phone_e164) not in response.text


async def test_mismo_sillon_con_otro_profesional_es_409(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    colega = await make_professional(db_session, agenda.staff.clinic, display_name="Dra. Ficticia")
    await make_schedule_rule(
        db_session,
        agenda.staff.clinic,
        colega,
        agenda.staff.chair,
        weekday=0,
        valid_from=date(2026, 1, 1),
        start_time=time(9),
        end_time=time(13),
        slot_duration_min=30,
    )
    # Dos reglas activas del mismo sillón el mismo día: el EXCLUDE de C-04 es por profesional.
    await seed(db_session, agenda, at(10))

    response = await post(app_client, agenda, at(10), professional_id=str(colega.id))

    assert response.status_code == 409
    assert response.json()["detail"] == "slot_taken"


async def test_contiguos_conviven(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    await seed(db_session, agenda, at(10))
    response = await post(app_client, agenda, at(10, 30))
    assert response.status_code == 201


async def test_el_buffer_integra_el_rango_ocupado(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    agenda.staff.professional.buffer_min = 10
    await db_session.flush()
    await seed(db_session, agenda, at(10), buffer_min=10)

    response = await post(app_client, agenda, at(10, 35))

    assert response.status_code == 409
    assert response.json()["detail"] == "slot_taken"


async def test_turno_cancelado_libera_el_hueco(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    await seed(
        db_session,
        agenda,
        at(10),
        status=AppointmentStatus.CANCELLED,
        cancelled_at=at(7),
        cancellation_reason=CancellationReason.PACIENTE,
    )
    response = await post(app_client, agenda, at(10))
    assert response.status_code == 201


async def test_alternativos_dentro_de_la_plantilla_en_orden(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    await seed(db_session, agenda, at(10))
    await seed(db_session, agenda, at(10, 30))
    await make_block(
        db_session,
        agenda.staff.clinic,
        chair=agenda.staff.chair,
        created_by_user_id=agenda.staff.admin.id,
        starts_at=at(11, 30),
        ends_at=at(12),
    )

    response = await post(app_client, agenda, at(10))

    assert response.status_code == 409
    alternativos = response.json()["alternatives"]
    assert [_instante(a["starts_at"]) for a in alternativos] == [at(11), at(12), at(12, 30)]
    assert alternativos[0] == {
        "starts_at": alternativos[0]["starts_at"],
        "ends_at": alternativos[0]["ends_at"],
        "professional_id": str(agenda.staff.professional.id),
        "chair_id": str(agenda.staff.chair.id),
    }
    assert _instante(alternativos[0]["ends_at"]) == at(11, 30)


async def test_sin_alternativos_en_14_dias(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings, valid_to=date(2030, 1, 7))
    for k in range(8):
        await seed(db_session, agenda, at(9) + timedelta(minutes=30 * k))

    response = await post(app_client, agenda, at(9))

    assert response.status_code == 409
    assert response.json()["alternatives"] == []


async def test_la_violacion_del_exclude_se_traduce_a_slot_taken(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin el chequeo previo del servicio, la base sigue siendo la barrera (regla dura 1)."""
    from app.modules.appointments import service as servicio

    agenda = await make_agenda(db_session, redis_client, settings)
    existente = await seed(db_session, agenda, at(10))

    async def _sin_conflictos(*_: object, **__: object) -> list[object]:
        return []

    monkeypatch.setattr(servicio, "find_conflicts", _sin_conflictos)
    response = await post(app_client, agenda, at(10))

    assert response.status_code == 409
    assert response.json()["detail"] == "slot_taken"
    monkeypatch.undo()
    assert existente.id is not None
