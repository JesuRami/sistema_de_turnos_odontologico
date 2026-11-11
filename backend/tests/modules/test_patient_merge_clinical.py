"""Fusión de pacientes con ficha clínica (C-15, D9, spec `core/patients`, Decisión 10)."""

from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest
from app.common.exceptions import DomainError
from app.core.settings import Settings
from app.models import ClinicalRecord, Patient, PatientMerge
from app.modules.clinical.service import RecordService
from app.modules.patients.merge import merge_patients
from app.modules.patients.schemas import PatientMergeRequest
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.clinical_helpers import (
    ClinicScene,
    count_rows,
    make_clinic_scene,
    make_committed_scene,
    open_record,
    principal_of,
)
from tests.factories import make_user

pytestmark = pytest.mark.integration


@pytest.fixture()
async def scene(db_session: AsyncSession, redis_client: Redis, settings: Settings) -> ClinicScene:
    return await make_clinic_scene(db_session, redis_client, settings)


async def _fusionar(
    client: httpx.AsyncClient, scene: ClinicScene, source: uuid.UUID, target: uuid.UUID
) -> httpx.Response:
    return await client.post(
        f"/api/patients/{source}/merge",
        json={"into_patient_id": str(target)},
        headers=scene.headers["recepcion"],
    )


async def test_absorbido_con_ficha_se_rechaza_sin_cambios(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    await open_record(app_client, scene)

    respuesta = await _fusionar(app_client, scene, scene.patient.id, scene.patient_b.id)

    assert (respuesta.status_code, respuesta.json()) == (
        409,
        {"detail": "patient_has_clinical_record"},
    )
    assert await count_rows(db_session, PatientMerge) == 0
    archivado = await db_session.scalar(
        select(Patient.archived_at)
        .where(Patient.id == scene.patient.id)
        .execution_options(populate_existing=True)
    )
    assert archivado is None


async def test_destino_con_ficha_procede(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)

    respuesta = await _fusionar(app_client, scene, scene.patient_b.id, scene.patient.id)

    assert respuesta.status_code == 200
    ficha = await db_session.scalar(
        select(ClinicalRecord.patient_id).where(ClinicalRecord.id == rid)
    )
    assert ficha == scene.patient.id


async def test_apertura_y_fusion_en_paralelo_nunca_quedan_ambas(
    committed_engine: AsyncEngine,
) -> None:
    async with AsyncSession(committed_engine, expire_on_commit=False) as session:
        s = await make_committed_scene(session)
        clinica = await session.scalar(select(Patient.clinic_id).where(Patient.id == s.patient_id))
        assert clinica is not None
        from app.models import Clinic

        recepcion = await make_user(
            session, await session.get(Clinic, clinica), role="recepcion"  # type: ignore[arg-type]
        )
        await session.commit()

    async def _abrir() -> str:
        async with AsyncSession(committed_engine, expire_on_commit=False) as session:
            try:
                await RecordService(session, principal_of(s.dentist)).open(s.patient_id)
            except DomainError as exc:
                return exc.detail
            return "abierta"

    async def _fusion() -> str:
        async with AsyncSession(committed_engine, expire_on_commit=False) as session:
            try:
                from datetime import UTC, datetime

                await merge_patients(
                    session,
                    principal_of(recepcion),
                    s.patient_id,
                    PatientMergeRequest(into_patient_id=s.other_patient_id),
                    datetime.now(UTC),
                )
            except DomainError as exc:
                return exc.detail
            return "fusionado"

    resultados = set(await asyncio.gather(_abrir(), _fusion()))

    assert resultados in (
        {"abierta", "patient_has_clinical_record"},
        {"fusionado", "patient_archived"},
    )
    async with AsyncSession(committed_engine) as session:
        fichas = await session.scalar(select(func.count()).select_from(ClinicalRecord))
        fusiones = await session.scalar(select(func.count()).select_from(PatientMerge))
    assert (fichas, fusiones) in ((1, 0), (0, 1))
