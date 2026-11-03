"""Consulta de agenda por rango con alcance por rol (C-05 tarea 8.1, D12)."""

from __future__ import annotations

from typing import Any, cast

import httpx
import pytest
from app.core.settings import Settings
from app.models import AppointmentStatus, CancellationReason
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tests.appointment_helpers import Agenda, at, iso, make_agenda, seed
from tests.conftest import MutableClock
from tests.factories import make_patient, make_professional

pytestmark = pytest.mark.integration


async def _listar(
    client: httpx.AsyncClient, agenda: Agenda, rol: str = "recepcion", /, **params: Any
) -> httpx.Response:
    valores: dict[str, Any] = {"from": iso(0), "to": iso(0, days=7)}
    valores.update(params)
    return await client.get("/api/appointments", params=valores, headers=agenda.headers[rol])


async def test_recepcion_lista_la_semana_por_inicio(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    colega = await make_professional(db_session, agenda.staff.clinic, display_name="Dra. Lista")
    tarde = await seed(db_session, agenda, at(12))
    temprano = await seed(db_session, agenda, at(9), professional=colega)
    await seed(db_session, agenda, at(10, days=7))  # fuera del rango

    response = await _listar(app_client, agenda)

    assert response.status_code == 200, response.text
    body = response.json()
    assert [a["id"] for a in body["items"]] == [str(temprano.id), str(tarde.id)]
    assert body["next_cursor"] is None
    assert body["items"][0]["patient"]["phone_e164"] == agenda.patient.phone_e164


async def test_odontologo_ve_solo_los_suyos_y_sin_contacto(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    colega = await make_professional(db_session, agenda.staff.clinic, display_name="Dra. Ajena")
    propio = await seed(db_session, agenda, at(10))
    ajeno = await seed(db_session, agenda, at(11), professional=colega)

    response = await _listar(app_client, agenda, "odontologo")
    detalle_ajeno = await app_client.get(
        f"/api/appointments/{ajeno.id}", headers=agenda.headers["odontologo"]
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert [a["id"] for a in items] == [str(propio.id)]
    assert set(items[0]["patient"]) == {"id", "full_name"}
    assert str(agenda.patient.phone_e164) not in response.text
    assert detalle_ajeno.status_code == 404


async def test_filtros_por_profesional_sillon_y_estado(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    colega = await make_professional(db_session, agenda.staff.clinic, display_name="Dra. Filtro")
    vigente = await seed(db_session, agenda, at(10))
    await seed(db_session, agenda, at(11), professional=colega)
    cancelado = await seed(
        db_session,
        agenda,
        at(12),
        status=AppointmentStatus.CANCELLED,
        cancelled_at=at(7),
        cancellation_reason=CancellationReason.OTRO,
    )

    por_prof = await _listar(app_client, agenda, professional_id=str(agenda.staff.professional.id))
    por_estado = await _listar(app_client, agenda, status=["cancelled"])
    por_sillon = await _listar(app_client, agenda, chair_id=str(agenda.staff.chair.id))

    assert [a["id"] for a in por_prof.json()["items"]] == [str(vigente.id), str(cancelado.id)]
    assert [a["id"] for a in por_estado.json()["items"]] == [str(cancelado.id)]
    assert len(por_sillon.json()["items"]) == 3


async def test_paginacion_por_cursor(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    paciente = await make_patient(db_session, agenda.staff.clinic, full_name="Otro Ficticio")
    ids = [str((await seed(db_session, agenda, at(9 + k))).id) for k in range(3)]
    ids.insert(
        1,
        str(
            (
                await seed(
                    db_session,
                    agenda,
                    at(9),
                    patient=paciente,
                    is_overbooking=True,
                    overbooking_reason="Sobre",
                )
            ).id
        ),
    )
    esperado = sorted(ids[:2]) + ids[2:]

    vistos: list[str] = []
    cursor = None
    for _ in range(3):
        params: dict[str, object] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        pagina = (await _listar(app_client, agenda, **params)).json()
        vistos += [a["id"] for a in pagina["items"]]
        cursor = pagina["next_cursor"]
        if cursor is None:
            break

    assert vistos == esperado


@pytest.mark.parametrize(
    "params",
    [
        {"from": iso(0), "to": iso(0, days=60)},
        {"from": iso(0, days=1), "to": iso(0)},
    ],
)
async def test_rango_invalido_es_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
    params: dict[str, object],
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    response = await _listar(app_client, agenda, **params)
    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_range"


@pytest.mark.parametrize(
    "params",
    [{"from": None}, {"to": "2030-01-08T00:00:00"}, {"limit": 501}, {"status": ["borrado"]}],
)
async def test_parametros_invalidos_son_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
    params: dict[str, object],
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    valores = {"from": iso(0), "to": iso(0, days=7), **params}
    response = await app_client.get(
        "/api/appointments",
        params=cast(Any, {k: v for k, v in valores.items() if v is not None}),
        headers=agenda.headers["admin"],
    )
    assert response.status_code == 422


async def test_detalle_de_un_turno(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await seed(db_session, agenda, at(10), notes="Nota operativa ficticia")
    response = await app_client.get(
        f"/api/appointments/{turno.id}", headers=agenda.headers["odontologo"]
    )
    assert response.status_code == 200
    assert response.json()["notes"] == "Nota operativa ficticia"
