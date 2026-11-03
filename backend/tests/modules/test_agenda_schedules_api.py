"""US-002: plantilla semanal — anti-solape en la base, recursos válidos, RBAC y auditoría."""

from __future__ import annotations

import uuid

import httpx
import pytest
from app.core.settings import Settings
from app.models import ConfigAction, ConfigEntity, ScheduleRule
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.agenda_helpers import Staff, actions, config_events, make_staff
from tests.factories import make_chair, make_professional, make_schedule_rule

pytestmark = pytest.mark.integration


def _regla(staff: Staff, **overrides: object) -> dict[str, object]:
    valores: dict[str, object] = {
        "professional_id": str(staff.professional.id),
        "chair_id": str(staff.chair.id),
        "weekday": 0,
        "start_time": "09:00",
        "end_time": "13:00",
        "slot_duration_min": 30,
        "valid_from": "2026-01-01",
    }
    valores.update(overrides)
    return valores


async def _crear(client: httpx.AsyncClient, staff: Staff, **overrides: object) -> httpx.Response:
    return await client.post(
        "/api/schedules", json=_regla(staff, **overrides), headers=staff.headers["admin"]
    )


async def test_admin_crea_regla_y_queda_auditada(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)

    response = await _crear(app_client, staff)

    assert response.status_code == 201
    body = response.json()
    assert (body["start_time"], body["end_time"], body["valid_to"]) == (
        "09:00:00",
        "13:00:00",
        None,
    )
    assert body["active"] is True
    eventos = await config_events(db_session, ConfigEntity.SCHEDULE_RULE, uuid.UUID(body["id"]))
    assert actions(eventos) == [ConfigAction.CREATED]


async def test_regla_solapada_es_409_con_las_reglas_en_conflicto(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    existente = (await _crear(app_client, staff)).json()

    response = await _crear(app_client, staff, start_time="12:00", end_time="15:00")

    assert response.status_code == 409
    assert response.json() == {"detail": "schedule_overlap", "conflicts": [existente["id"]]}
    total = await db_session.scalar(
        select(func.count())
        .select_from(ScheduleRule)
        .where(ScheduleRule.professional_id == staff.professional.id)
    )
    assert total == 1


async def test_franjas_contiguas_conviven(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    await _crear(app_client, staff)

    response = await _crear(app_client, staff, start_time="13:00", end_time="17:00")

    assert response.status_code == 201


async def test_desactivar_libera_la_franja_y_reactivar_vuelve_a_chocar(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    primera = (await _crear(app_client, staff)).json()
    url = f"/api/schedules/{primera['id']}"

    baja = await app_client.patch(url, json={"active": False}, headers=staff.headers["admin"])
    segunda = await _crear(app_client, staff, start_time="10:00", end_time="12:00")
    reactivar = await app_client.patch(url, json={"active": True}, headers=staff.headers["admin"])

    assert baja.status_code == 200
    assert segunda.status_code == 201
    assert reactivar.status_code == 409
    assert reactivar.json()["conflicts"] == [segunda.json()["id"]]
    eventos = await config_events(db_session, ConfigEntity.SCHEDULE_RULE, uuid.UUID(primera["id"]))
    assert actions(eventos) == [ConfigAction.CREATED, ConfigAction.DEACTIVATED]


async def test_editar_franja_y_cerrar_vigencia(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    regla = (await _crear(app_client, staff)).json()

    response = await app_client.patch(
        f"/api/schedules/{regla['id']}",
        json={"end_time": "14:00", "valid_to": "2026-12-31"},
        headers=staff.headers["admin"],
    )

    assert response.status_code == 200
    assert (response.json()["end_time"], response.json()["valid_to"]) == ("14:00:00", "2026-12-31")
    eventos = await config_events(db_session, ConfigEntity.SCHEDULE_RULE, uuid.UUID(regla["id"]))
    assert eventos[-1].changes == {
        "end_time": ["13:00:00", "14:00:00"],
        "valid_to": [None, "2026-12-31"],
    }


async def test_edicion_que_invierte_la_franja_es_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    regla = (await _crear(app_client, staff)).json()

    response = await app_client.patch(
        f"/api/schedules/{regla['id']}", json={"end_time": "08:00"}, headers=staff.headers["admin"]
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_schedule_rule"}


@pytest.mark.parametrize(
    "invalido",
    [
        {"start_time": "13:00", "end_time": "09:00"},
        {"weekday": 7},
        {"slot_duration_min": 300},
        {"valid_from": "2026-06-02", "valid_to": "2026-06-01"},
        {"clinic_id": str(uuid.uuid4())},
    ],
)
async def test_regla_invalida_es_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    invalido: dict[str, object],
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    assert (await _crear(app_client, staff, **invalido)).status_code == 422


async def test_recurso_inactivo_es_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    inactivo = await make_professional(db_session, staff.clinic, active=False)
    sillon_inactivo = await make_chair(db_session, staff.clinic, active=False)

    por_profesional = await _crear(app_client, staff, professional_id=str(inactivo.id))
    por_sillon = await _crear(app_client, staff, chair_id=str(sillon_inactivo.id))

    assert por_profesional.json() == {"detail": "resource_inactive"}
    assert por_sillon.status_code == 422


async def test_sillon_de_otra_clinica_es_422_sin_revelarlo(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    otra = await make_staff(db_session, redis_client, settings)

    response = await _crear(app_client, staff, chair_id=str(otra.chair.id))

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_resource"}


@pytest.mark.parametrize("rol", ["recepcion", "odontologo"])
async def test_solo_admin_escribe_reglas(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    rol: str,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    response = await app_client.post(
        "/api/schedules", json=_regla(staff), headers=staff.headers[rol]
    )
    assert response.status_code == 403


async def test_lectura_por_rol_y_filtros(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    colega = await make_professional(db_session, staff.clinic, display_name="Dr. Ficticio Colega")
    propia = await make_schedule_rule(db_session, staff.clinic, staff.professional, staff.chair)
    ajena = await make_schedule_rule(db_session, staff.clinic, colega, staff.chair, weekday=2)

    recepcion = await app_client.get("/api/schedules", headers=staff.headers["recepcion"])
    filtrada = await app_client.get(
        "/api/schedules",
        params={"professional_id": str(colega.id)},
        headers=staff.headers["recepcion"],
    )
    odontologo = await app_client.get("/api/schedules", headers=staff.headers["odontologo"])
    ajena_por_id = await app_client.get(
        f"/api/schedules/{ajena.id}", headers=staff.headers["odontologo"]
    )

    assert {i["id"] for i in recepcion.json()["items"]} == {str(propia.id), str(ajena.id)}
    assert [i["id"] for i in filtrada.json()["items"]] == [str(ajena.id)]
    assert [i["id"] for i in odontologo.json()["items"]] == [str(propia.id)]
    assert ajena_por_id.status_code == 404


async def test_admin_de_otra_clinica_no_ve_ni_edita_reglas(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    otra = await make_staff(db_session, redis_client, settings)
    regla = await make_schedule_rule(db_session, staff.clinic, staff.professional, staff.chair)

    listado = await app_client.get("/api/schedules", headers=otra.headers["admin"])
    edicion = await app_client.patch(
        f"/api/schedules/{regla.id}", json={"active": False}, headers=otra.headers["admin"]
    )

    assert listado.json()["items"] == []
    assert edicion.status_code == 404
