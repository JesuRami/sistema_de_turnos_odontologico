"""Auditoría de acceso clínico (C-15, D5). Postgres + Redis reales, datos sintéticos.

Escenarios: "Lectura auditada", "Descarga y PDF auditados" (en sus módulos), "Falla de auditoría
revierte la operación", "Admin pagina la bitácora", "Odontólogo no ve la bitácora".
"""

from __future__ import annotations

import json
from datetime import datetime

import httpx
import pytest
from app.core.settings import Settings
from app.models import ClinicalAccessEvent, ClinicalAction, ClinicalRecord
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.clinical_helpers import (
    DNI_FICTICIO,
    NOMBRE_PACIENTE,
    ClinicScene,
    access_events,
    count_rows,
    make_clinic_scene,
    open_record,
    seed_catalog,
)

pytestmark = pytest.mark.integration


@pytest.fixture()
async def scene(db_session: AsyncSession, redis_client: Redis, settings: Settings) -> ClinicScene:
    s = await make_clinic_scene(db_session, redis_client, settings)
    await seed_catalog(db_session, s.clinic)
    return s


def _sin_pii(evento: ClinicalAccessEvent, scene: ClinicScene) -> None:
    crudo = json.dumps(evento.payload, ensure_ascii=False)
    for sensible in (NOMBRE_PACIENTE, DNI_FICTICIO, scene.patient.phone_e164 or "+54"):
        assert sensible not in crudo


async def test_apertura_y_lectura_dejan_un_evento_cada_una(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)
    await app_client.get(
        f"/api/patients/{scene.patient.id}/clinical-record", headers=scene.headers["odontologo"]
    )

    eventos = await access_events(db_session)
    assert [e.action for e in eventos] == [ClinicalAction.RECORD_OPEN, ClinicalAction.RECORD_READ]
    for evento in eventos:
        assert evento.record_id == rid
        assert evento.actor_user_id == scene.users["odontologo"].id
        assert evento.clinic_id == scene.clinic.id
        _sin_pii(evento, scene)


async def test_reapertura_se_audita_como_lectura(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    await open_record(app_client, scene)
    await open_record(app_client, scene, "admin_prof")

    acciones = [e.action for e in await access_events(db_session)]
    assert acciones == [ClinicalAction.RECORD_OPEN, ClinicalAction.RECORD_READ]


async def test_falla_de_auditoria_revierte_la_operacion(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    """Un trigger temporal hace fallar el INSERT del evento: no queda la ficha y responde 500."""
    await db_session.execute(
        text(
            "CREATE FUNCTION test_falla_auditoria() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN RAISE EXCEPTION 'falla inyectada'; END; $$"
        )
    )
    await db_session.execute(
        text(
            "CREATE TRIGGER trg_test_falla BEFORE INSERT ON clinical_access_event "
            "FOR EACH ROW EXECUTE FUNCTION test_falla_auditoria()"
        )
    )

    respuesta = await app_client.post(
        f"/api/patients/{scene.patient.id}/clinical-record", headers=scene.headers["odontologo"]
    )
    await db_session.rollback()

    assert respuesta.status_code == 500
    assert respuesta.json()["detail"] == "internal_error"
    assert "falla inyectada" not in respuesta.text
    assert await count_rows(db_session, ClinicalRecord) == 0
    assert await count_rows(db_session, ClinicalAccessEvent) == 0


async def test_admin_pagina_la_bitacora(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)
    db_session.add_all(
        [
            ClinicalAccessEvent(
                clinic_id=scene.clinic.id,
                record_id=rid,
                actor_user_id=scene.users["odontologo"].id,
                action=ClinicalAction.RECORD_READ,
            )
            for _ in range(119)
        ]
    )
    await db_session.flush()
    path = f"/api/clinical-records/{rid}/access-log"
    headers = scene.headers["admin"]

    primera = (await app_client.get(path, params={"limit": 50}, headers=headers)).json()
    segunda = (
        await app_client.get(
            path, params={"limit": 50, "cursor": primera["next_cursor"]}, headers=headers
        )
    ).json()
    tercera = (
        await app_client.get(
            path, params={"limit": 50, "cursor": segunda["next_cursor"]}, headers=headers
        )
    ).json()

    assert [len(p["items"]) for p in (primera, segunda, tercera)] == [50, 50, 20]
    assert tercera["next_cursor"] is None
    instantes = [
        datetime.fromisoformat(i["created_at"])
        for p in (primera, segunda, tercera)
        for i in p["items"]
    ]
    assert instantes == sorted(instantes, reverse=True)
    ids = [i["id"] for p in (primera, segunda, tercera) for i in p["items"]]
    assert len(set(ids)) == 120
    assert tercera["items"][-1]["action"] == "record_open"


@pytest.mark.parametrize("limit", [0, 101])
async def test_limite_invalido_de_la_bitacora(
    app_client: httpx.AsyncClient, scene: ClinicScene, limit: int
) -> None:
    rid = await open_record(app_client, scene)

    respuesta = await app_client.get(
        f"/api/clinical-records/{rid}/access-log",
        params={"limit": limit},
        headers=scene.headers["admin"],
    )

    assert respuesta.status_code == 422


async def test_odontologo_no_ve_la_bitacora(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)

    respuesta = await app_client.get(
        f"/api/clinical-records/{rid}/access-log", headers=scene.headers["odontologo"]
    )

    assert (respuesta.status_code, respuesta.json()) == (403, {"detail": "forbidden_role"})
    assert [e.action for e in await access_events(db_session)] == [ClinicalAction.RECORD_OPEN]
