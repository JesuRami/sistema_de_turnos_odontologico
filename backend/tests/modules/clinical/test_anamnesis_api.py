"""Anamnesis versionada e inmutable (C-15, spec `clinical/patient-record`, Decisión 9).

Postgres + Redis reales; el conflicto concurrente usa dos sesiones con commits reales.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest
from app.common.exceptions import DomainError
from app.core.settings import Settings
from app.models import AnamnesisVersion, ClinicalAccessEvent, ClinicalAction
from app.modules.clinical.schemas import AnamnesisAnswers, AnamnesisCreate
from app.modules.clinical.service import AnamnesisService, RecordService
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.clinical_helpers import (
    ClinicScene,
    access_events,
    count_rows,
    make_clinic_scene,
    make_committed_scene,
    open_record,
    principal_of,
)

pytestmark = pytest.mark.integration

RESPUESTAS = {
    "allergies": ["Penicilina ficticia"],
    "medications": [],
    "systemic_conditions": ["hipertension"],
    "pregnant": None,
    "smoker": False,
    "anticoagulants": False,
    "observations": "Observación sintética",
}


@pytest.fixture()
async def scene(db_session: AsyncSession, redis_client: Redis, settings: Settings) -> ClinicScene:
    return await make_clinic_scene(db_session, redis_client, settings)


async def _guardar(
    client: httpx.AsyncClient,
    scene: ClinicScene,
    rid: uuid.UUID,
    expected: int,
    answers: dict[str, Any],
    rol: str = "odontologo",
) -> httpx.Response:
    return await client.post(
        f"/api/clinical-records/{rid}/anamnesis",
        json={"expected_version": expected, "answers": answers},
        headers=scene.headers[rol],
    )


async def test_primera_version(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)

    respuesta = await _guardar(app_client, scene, rid, 0, RESPUESTAS)

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["version"] == 1
    assert cuerpo["created_by_user_id"] == str(scene.users["odontologo"].id)
    assert cuerpo["answers"]["allergies"] == ["Penicilina ficticia"]
    assert (await access_events(db_session))[-1].action is ClinicalAction.ANAMNESIS_WRITE


async def test_correccion_crea_version_2_y_conserva_la_1(
    app_client: httpx.AsyncClient, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)
    await _guardar(app_client, scene, rid, 0, RESPUESTAS)

    segunda = await _guardar(
        app_client, scene, rid, 1, {**RESPUESTAS, "allergies": ["Látex ficticio"]}
    )
    vigente = await app_client.get(
        f"/api/clinical-records/{rid}/anamnesis", headers=scene.headers["odontologo"]
    )
    versiones = await app_client.get(
        f"/api/clinical-records/{rid}/anamnesis/versions", headers=scene.headers["admin"]
    )

    assert segunda.status_code == 201
    assert vigente.json()["version"] == 2
    assert vigente.json()["answers"]["allergies"] == ["Látex ficticio"]
    items = versiones.json()["items"]
    assert [i["version"] for i in items] == [2, 1]
    assert items[1]["answers"]["allergies"] == ["Penicilina ficticia"]


async def test_version_desactualizada_es_409(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)
    await _guardar(app_client, scene, rid, 0, RESPUESTAS)
    await _guardar(app_client, scene, rid, 1, RESPUESTAS)
    eventos = await count_rows(db_session, ClinicalAccessEvent)

    vieja = await _guardar(app_client, scene, rid, 1, RESPUESTAS)

    assert (vieja.status_code, vieja.json()) == (409, {"detail": "version_conflict"})
    assert await count_rows(db_session, AnamnesisVersion) == 2
    assert await count_rows(db_session, ClinicalAccessEvent) == eventos


async def test_dos_guardados_concurrentes_solo_uno_gana(committed_engine: AsyncEngine) -> None:
    async with AsyncSession(committed_engine, expire_on_commit=False) as session:
        s = await make_committed_scene(session)
    principal = principal_of(s.dentist)
    async with AsyncSession(committed_engine, expire_on_commit=False) as session:
        ficha = await RecordService(session, principal).open(s.patient_id)
        await AnamnesisService(session, principal).create(
            ficha.record_id, AnamnesisCreate(expected_version=0, answers=AnamnesisAnswers())
        )

    async def _guardar_v2(alergia: str) -> int:
        async with AsyncSession(committed_engine, expire_on_commit=False) as session:
            try:
                creada = await AnamnesisService(session, principal).create(
                    ficha.record_id,
                    AnamnesisCreate(
                        expected_version=1, answers=AnamnesisAnswers(allergies=[alergia])
                    ),
                )
            except DomainError as exc:
                assert exc.detail == "version_conflict"
                return exc.status_code
            return 201 if creada.version == 2 else 500

    resultados = await asyncio.gather(_guardar_v2("Alergia ficticia A"), _guardar_v2("B ficticia"))

    assert sorted(resultados) == [201, 409]
    async with AsyncSession(committed_engine) as session:
        maximo = await session.scalar(select(func.max(AnamnesisVersion.version)))
        assert maximo == 2


async def test_observaciones_de_1001_caracteres_es_422(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)
    texto = "x" * 1001

    respuesta = await _guardar(app_client, scene, rid, 0, {**RESPUESTAS, "observations": texto})

    assert respuesta.status_code == 422
    assert texto not in respuesta.text
    assert await count_rows(db_session, AnamnesisVersion) == 0


async def test_observaciones_de_1000_caracteres_se_acepta(
    app_client: httpx.AsyncClient, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)

    respuesta = await _guardar(
        app_client, scene, rid, 0, {**RESPUESTAS, "observations": "y" * 1000}
    )

    assert respuesta.status_code == 201


@pytest.mark.parametrize(
    "answers",
    [
        {**RESPUESTAS, "campo_fantasma": True},
        {**RESPUESTAS, "systemic_conditions": ["condicion_inventada"]},
        {**RESPUESTAS, "smoker": "quizas"},
    ],
    ids=["extra", "condicion_desconocida", "tipo_invalido"],
)
async def test_cuerpo_invalido_es_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    scene: ClinicScene,
    answers: dict[str, Any],
) -> None:
    rid = await open_record(app_client, scene)

    respuesta = await _guardar(app_client, scene, rid, 0, answers)

    assert respuesta.status_code == 422
    assert await count_rows(db_session, AnamnesisVersion) == 0


async def test_campo_extra_en_la_raiz_es_422(
    app_client: httpx.AsyncClient, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)

    respuesta = await app_client.post(
        f"/api/clinical-records/{rid}/anamnesis",
        json={"expected_version": 0, "answers": {}, "created_by_user_id": str(uuid.uuid4())},
        headers=scene.headers["odontologo"],
    )

    assert respuesta.status_code == 422


async def test_anamnesis_vacia_es_version_1(
    app_client: httpx.AsyncClient, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)
    vacia = {
        "allergies": [],
        "medications": [],
        "systemic_conditions": [],
        "smoker": False,
        "anticoagulants": False,
    }

    respuesta = await _guardar(app_client, scene, rid, 0, vacia)

    assert respuesta.status_code == 201
    assert respuesta.json()["version"] == 1


async def test_sin_anamnesis_la_vigente_es_null_y_se_audita(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)

    respuesta = await app_client.get(
        f"/api/clinical-records/{rid}/anamnesis", headers=scene.headers["odontologo"]
    )

    assert respuesta.status_code == 200
    assert respuesta.json() is None
    assert (await access_events(db_session))[-1].action is ClinicalAction.ANAMNESIS_READ
