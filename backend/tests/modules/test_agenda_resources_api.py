"""US-001: profesionales y sillones — CRUD admin, lectura por rol, baja lógica y auditoría."""

from __future__ import annotations

import uuid

import httpx
import pytest
from app.core.settings import Settings
from app.models import Chair, ConfigAction, ConfigEntity, Professional
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.agenda_helpers import actions, config_events, make_staff
from tests.factories import make_chair, make_clinic, make_professional

pytestmark = pytest.mark.integration


def _profesional(**overrides: object) -> dict[str, object]:
    valores: dict[str, object] = {
        "display_name": "Dra. Ficticia Dos",
        "color": "#1E90FF",
        "default_duration_min": 40,
        "buffer_min": 10,
    }
    valores.update(overrides)
    return valores


# ------------------------------------------------------------ profesionales


async def test_admin_crea_profesional_y_queda_auditado(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)

    response = await app_client.post(
        "/api/professionals", json=_profesional(), headers=staff.headers["admin"]
    )

    assert response.status_code == 201
    body = response.json()
    assert body["display_name"] == "Dra. Ficticia Dos"
    assert (body["color"], body["default_duration_min"], body["buffer_min"]) == (
        "#1E90FF",
        40,
        10,
    )
    assert body["active"] is True
    assert body["booking_enabled"] is True
    eventos = await config_events(db_session, ConfigEntity.PROFESSIONAL, uuid.UUID(body["id"]))
    assert actions(eventos) == [ConfigAction.CREATED]
    assert eventos[0].actor_user_id == staff.admin.id
    assert eventos[0].clinic_id == staff.clinic.id


@pytest.mark.parametrize(
    "invalido",
    [
        {"color": "azul"},
        {"default_duration_min": 0},
        {"buffer_min": -5},
        {"display_name": "   "},
        {"clinic_id": str(uuid.uuid4())},
    ],
)
async def test_alta_de_profesional_invalida_es_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    invalido: dict[str, object],
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    response = await app_client.post(
        "/api/professionals", json=_profesional(**invalido), headers=staff.headers["admin"]
    )
    assert response.status_code == 422


async def test_admin_desactiva_y_reactiva_profesional_sin_borrarlo(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    url = f"/api/professionals/{staff.professional.id}"

    baja = await app_client.patch(url, json={"active": False}, headers=staff.headers["admin"])
    alta = await app_client.patch(url, json={"active": True}, headers=staff.headers["admin"])

    assert baja.status_code == 200
    assert baja.json()["active"] is False
    assert alta.json()["active"] is True
    fila = await db_session.scalar(
        select(Professional).where(Professional.id == staff.professional.id)
    )
    assert fila is not None
    eventos = await config_events(db_session, ConfigEntity.PROFESSIONAL, staff.professional.id)
    assert actions(eventos) == [ConfigAction.DEACTIVATED, ConfigAction.REACTIVATED]
    assert eventos[0].changes == {"active": [True, False]}


async def test_edicion_audita_valor_anterior_y_nuevo(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)

    response = await app_client.patch(
        f"/api/professionals/{staff.professional.id}",
        json={"buffer_min": 15, "color": None},
        headers=staff.headers["admin"],
    )

    assert response.status_code == 200
    eventos = await config_events(db_session, ConfigEntity.PROFESSIONAL, staff.professional.id)
    assert actions(eventos) == [ConfigAction.UPDATED]
    assert eventos[0].changes == {"buffer_min": [0, 15]}


async def test_patch_con_null_en_campo_obligatorio_es_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    response = await app_client.patch(
        f"/api/professionals/{staff.professional.id}",
        json={"display_name": None},
        headers=staff.headers["admin"],
    )
    assert response.status_code == 422


@pytest.mark.parametrize("rol", ["recepcion", "odontologo"])
async def test_solo_admin_escribe_profesionales(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    rol: str,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)

    alta = await app_client.post(
        "/api/professionals", json=_profesional(), headers=staff.headers[rol]
    )
    edicion = await app_client.patch(
        f"/api/professionals/{staff.professional.id}",
        json={"buffer_min": 5},
        headers=staff.headers[rol],
    )

    assert (alta.status_code, edicion.status_code) == (403, 403)
    assert alta.json() == {"detail": "forbidden_role"}


async def test_recepcion_lista_todos_y_filtra_activos(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    inactivo = await make_professional(
        db_session, staff.clinic, display_name="Dr. Ficticio Inactivo", active=False
    )

    todos = await app_client.get("/api/professionals", headers=staff.headers["recepcion"])
    activos = await app_client.get(
        "/api/professionals", params={"active": "true"}, headers=staff.headers["recepcion"]
    )

    ids_todos = {item["id"] for item in todos.json()["items"]}
    ids_activos = {item["id"] for item in activos.json()["items"]}
    assert ids_todos == {str(staff.professional.id), str(inactivo.id)}
    assert ids_activos == {str(staff.professional.id)}


async def test_listado_pagina_por_cursor(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    for n in range(3):
        await make_professional(db_session, staff.clinic, display_name=f"Dr. Ficticio {n}")

    vistos: list[str] = []
    cursor: str | None = None
    for _ in range(5):
        params: dict[str, str | int] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        pagina = (
            await app_client.get(
                "/api/professionals", params=params, headers=staff.headers["admin"]
            )
        ).json()
        vistos += [item["id"] for item in pagina["items"]]
        cursor = pagina["next_cursor"]
        if cursor is None:
            break

    assert len(vistos) == 4
    assert len(set(vistos)) == 4


async def test_odontologo_solo_ve_su_profesional(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    colega = await make_professional(db_session, staff.clinic, display_name="Dr. Ficticio Colega")

    listado = await app_client.get("/api/professionals", headers=staff.headers["odontologo"])
    propio = await app_client.get(
        f"/api/professionals/{staff.professional.id}", headers=staff.headers["odontologo"]
    )
    ajeno = await app_client.get(
        f"/api/professionals/{colega.id}", headers=staff.headers["odontologo"]
    )

    assert [item["id"] for item in listado.json()["items"]] == [str(staff.professional.id)]
    assert propio.status_code == 200
    assert ajeno.status_code == 404
    assert ajeno.json() == {"detail": "not_found"}


async def test_admin_de_otra_clinica_no_ve_ni_edita(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    otra = await make_staff(db_session, redis_client, settings)
    url = f"/api/professionals/{staff.professional.id}"

    lectura = await app_client.get(url, headers=otra.headers["admin"])
    edicion = await app_client.patch(url, json={"active": False}, headers=otra.headers["admin"])
    listado = await app_client.get("/api/professionals", headers=otra.headers["admin"])

    assert (lectura.status_code, edicion.status_code) == (404, 404)
    assert str(staff.professional.id) not in {i["id"] for i in listado.json()["items"]}
    await db_session.refresh(staff.professional)
    assert staff.professional.active is True


# ------------------------------------------------------------------ sillones


async def test_admin_crea_renombra_y_desactiva_sillon(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)

    alta = await app_client.post(
        "/api/chairs", json={"name": "Box Ficticio 2"}, headers=staff.headers["admin"]
    )
    chair_id = alta.json()["id"]
    renombre = await app_client.patch(
        f"/api/chairs/{chair_id}", json={"name": "Box Ficticio B"}, headers=staff.headers["admin"]
    )
    baja = await app_client.patch(
        f"/api/chairs/{chair_id}", json={"active": False}, headers=staff.headers["admin"]
    )

    assert alta.status_code == 201
    assert renombre.json()["name"] == "Box Ficticio B"
    assert baja.json()["active"] is False
    eventos = await config_events(db_session, ConfigEntity.CHAIR, uuid.UUID(chair_id))
    assert actions(eventos) == [
        ConfigAction.CREATED,
        ConfigAction.UPDATED,
        ConfigAction.DEACTIVATED,
    ]
    assert await db_session.scalar(select(Chair.id).where(Chair.id == uuid.UUID(chair_id)))


@pytest.mark.parametrize("rol", ["recepcion", "odontologo"])
async def test_todo_el_personal_lee_sillones_pero_no_los_escribe(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    rol: str,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    ajena = await make_clinic(db_session)
    await make_chair(db_session, ajena, name="Sillón Ficticio Ajeno")

    listado = await app_client.get("/api/chairs", headers=staff.headers[rol])
    alta = await app_client.post("/api/chairs", json={"name": "X"}, headers=staff.headers[rol])

    assert [item["id"] for item in listado.json()["items"]] == [str(staff.chair.id)]
    assert alta.status_code == 403


async def test_sillon_de_otra_clinica_es_404(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    otra = await make_staff(db_session, redis_client, settings)

    response = await app_client.patch(
        f"/api/chairs/{staff.chair.id}", json={"name": "Hackeado"}, headers=otra.headers["admin"]
    )

    assert response.status_code == 404
    await db_session.refresh(staff.chair)
    assert staff.chair.name == "Sillón Ficticio"
