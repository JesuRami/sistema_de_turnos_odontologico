"""Ficha clínica (C-15, spec `clinical/patient-record`): apertura idempotente, consulta y
paciente archivado. Postgres + Redis reales; la carrera usa commits reales.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
import pytest
from app.core.settings import Settings
from app.models import (
    AnamnesisVersion,
    ClinicalAccessEvent,
    ClinicalAction,
    ClinicalAttachment,
    ClinicalAttachmentRemoval,
    ClinicalEvolution,
    ClinicalRecord,
    EvolutionKind,
    Patient,
)
from app.modules.clinical.service import RecordService
from redis.asyncio import Redis
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.clinical_helpers import (
    NOMBRE_PACIENTE,
    ClinicScene,
    access_events,
    count_rows,
    make_clinic_scene,
    make_committed_scene,
    open_record,
    principal_of,
)

pytestmark = pytest.mark.integration


@pytest.fixture()
async def scene(db_session: AsyncSession, redis_client: Redis, settings: Settings) -> ClinicScene:
    return await make_clinic_scene(db_session, redis_client, settings)


def _path(scene: ClinicScene) -> str:
    return f"/api/patients/{scene.patient.id}/clinical-record"


async def test_primera_apertura_crea_la_ficha(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    respuesta = await app_client.post(_path(scene), headers=scene.headers["odontologo"])

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["patient_id"] == str(scene.patient.id)
    assert cuerpo["created"] is True
    assert await count_rows(db_session, ClinicalRecord) == 1
    assert [e.action for e in await access_events(db_session)] == [ClinicalAction.RECORD_OPEN]


async def test_apertura_repetida_devuelve_la_misma_ficha(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    primera = await app_client.post(_path(scene), headers=scene.headers["odontologo"])
    segunda = await app_client.post(_path(scene), headers=scene.headers["odontologo"])

    assert (primera.status_code, segunda.status_code) == (201, 200)
    assert segunda.json()["record_id"] == primera.json()["record_id"]
    assert segunda.json()["created"] is False
    assert await count_rows(db_session, ClinicalRecord) == 1


async def test_apertura_simultanea_deja_una_sola_ficha(committed_engine: AsyncEngine) -> None:
    async with AsyncSession(committed_engine, expire_on_commit=False) as session:
        s = await make_committed_scene(session)
    principal = principal_of(s.dentist)

    async def _abrir() -> object:
        async with AsyncSession(committed_engine, expire_on_commit=False) as session:
            return await RecordService(session, principal).open(s.patient_id)

    a, b = await asyncio.gather(_abrir(), _abrir())

    assert a.record_id == b.record_id  # type: ignore[attr-defined]
    assert sorted([a.created, b.created]) == [False, True]  # type: ignore[attr-defined]
    async with AsyncSession(committed_engine) as session:
        assert await session.scalar(select(func.count()).select_from(ClinicalRecord)) == 1


async def test_paciente_fusionado_no_abre_ficha(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    await db_session.execute(
        update(Patient)
        .where(Patient.id == scene.patient.id)
        .values(archived_at=datetime.now(UTC), merged_into_patient_id=scene.patient_b.id)
    )

    respuesta = await app_client.post(_path(scene), headers=scene.headers["odontologo"])

    assert (respuesta.status_code, respuesta.json()) == (409, {"detail": "patient_archived"})
    assert await count_rows(db_session, ClinicalRecord) == 0
    assert await count_rows(db_session, ClinicalAccessEvent) == 0


async def test_ficha_no_abierta(app_client: httpx.AsyncClient, scene: ClinicScene) -> None:
    respuesta = await app_client.get(_path(scene), headers=scene.headers["odontologo"])

    assert (respuesta.status_code, respuesta.json()) == (
        404,
        {"detail": "clinical_record_not_opened"},
    )


async def test_ficha_con_contenido_trae_la_vigente_y_los_conteos(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)
    autor = scene.users["odontologo"].id
    for version in (1, 2):
        db_session.add(
            AnamnesisVersion(
                clinic_id=scene.clinic.id,
                record_id=rid,
                version=version,
                answers={"smoker": version == 2},
                created_by_user_id=autor,
            )
        )
    for n in range(3):
        db_session.add(
            ClinicalEvolution(
                clinic_id=scene.clinic.id,
                record_id=rid,
                professional_id=scene.professional.id,
                created_by_user_id=autor,
                kind=EvolutionKind.ENTRY,
                body=f"Evolución sintética {n}",
                signed_at=datetime.now(UTC),
                content_sha256="b" * 64,
            )
        )
    adjunto = ClinicalAttachment(
        clinic_id=scene.clinic.id,
        record_id=rid,
        kind="photo",
        content_type="image/png",
        size_bytes=10,
        sha256="c" * 64,
        display_name="foto.png",
        storage_key=f"{scene.clinic.id}/clave-sintetica",
        created_by_user_id=autor,
    )
    db_session.add(adjunto)
    await db_session.flush()
    db_session.add(
        ClinicalAttachmentRemoval(
            clinic_id=scene.clinic.id,
            attachment_id=adjunto.id,
            reason="Motivo ficticio de baja",
            removed_by_user_id=autor,
        )
    )
    await db_session.flush()

    cuerpo = (await app_client.get(_path(scene), headers=scene.headers["odontologo"])).json()

    assert cuerpo["record_id"] == str(rid)
    assert cuerpo["patient_name"] == NOMBRE_PACIENTE
    assert cuerpo["anamnesis"]["version"] == 2
    assert cuerpo["anamnesis"]["answers"] == {"smoker": True}
    assert (cuerpo["evolutions_count"], cuerpo["attachments_count"], cuerpo["plans_count"]) == (
        3,
        0,
        0,
    )


async def test_paciente_archivado_se_lee_pero_no_se_escribe(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)
    await db_session.execute(
        update(Patient).where(Patient.id == scene.patient.id).values(archived_at=datetime.now(UTC))
    )

    escritura = await app_client.post(
        f"/api/clinical-records/{rid}/anamnesis",
        json={"expected_version": 0, "answers": {}},
        headers=scene.headers["odontologo"],
    )
    lectura = await app_client.get(_path(scene), headers=scene.headers["odontologo"])

    assert (escritura.status_code, escritura.json()) == (409, {"detail": "patient_archived"})
    assert await count_rows(db_session, AnamnesisVersion) == 0
    assert lectura.status_code == 200
    assert lectura.json()["patient_archived"] is True
    assert (await access_events(db_session))[-1].action is ClinicalAction.RECORD_READ
