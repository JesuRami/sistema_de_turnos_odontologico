"""Presupuestos por fases y PDF (C-15, D8, spec `clinical/treatment-plans`).

Postgres + Redis reales; la decisión concurrente usa commits reales. El texto del PDF se extrae
con `pypdf`. Datos sintéticos.
"""

from __future__ import annotations

import asyncio
import io
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from app.common.exceptions import DomainError
from app.core.settings import Settings
from app.models import ClinicalAction, Patient, TreatmentPlanDecision, TreatmentPlanVersion
from app.modules.clinical.plans import PlanService
from app.modules.clinical.schemas import DecisionCreate, PlanCreate, PlanItemIn
from app.modules.clinical.service import RecordService
from fastapi import FastAPI
from pypdf import PdfReader
from redis.asyncio import Redis
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.clinical_helpers import (
    DNI_FICTICIO,
    ClinicScene,
    access_events,
    count_rows,
    make_clinic_scene,
    make_committed_scene,
    open_record,
    principal_of,
)

pytestmark = pytest.mark.integration

ITEMS = [
    {"phase": 1, "description": "Obturación ficticia", "quantity": 2, "unit_price_cents": 15000},
    {
        "phase": 1,
        "description": "Cóndilo/Ø ficticio",
        "quantity": 1,
        "unit_price_cents": 5000,
        "tooth": 36,
        "surface": "O",
    },
    {"phase": 2, "description": "Corona ficticia", "quantity": 1, "unit_price_cents": 80000},
]


@pytest.fixture()
async def scene(db_session: AsyncSession, redis_client: Redis, settings: Settings) -> ClinicScene:
    return await make_clinic_scene(db_session, redis_client, settings)


async def _plan(
    client: httpx.AsyncClient,
    scene: ClinicScene,
    rid: uuid.UUID,
    items: list[dict[str, Any]],
    **extra: Any,
) -> httpx.Response:
    return await client.post(
        f"/api/clinical-records/{rid}/treatment-plans",
        json={"title": "Plan ficticio", "items": items, **extra},
        headers=scene.headers["odontologo"],
    )


async def test_plan_con_dos_fases_y_totales_del_servidor(
    app_client: httpx.AsyncClient, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)

    respuesta = await _plan(app_client, scene, rid, ITEMS)

    assert respuesta.status_code == 201
    version = respuesta.json()["versions"][0]
    assert version["version"] == 1
    assert [(f["phase"], f["subtotal_cents"], len(f["items"])) for f in version["phases"]] == [
        (1, 35000, 2),
        (2, 80000, 1),
    ]
    assert version["total_cents"] == 115000


@pytest.mark.parametrize(
    ("items", "extra", "detalle"),
    [
        ([{**ITEMS[0], "phase": 1}, {**ITEMS[2], "phase": 3}], {}, "invalid_phases"),
        ([], {}, None),
        ([ITEMS[0]] * 51, {}, None),
        ([{**ITEMS[0], "phase": 11}], {}, None),
        ([{**ITEMS[0], "unit_price_cents": -1}], {}, None),
        ([{**ITEMS[0], "unit_price_cents": 1.5}], {}, None),
        ([{**ITEMS[0], "quantity": 0}], {}, None),
        ([{**ITEMS[0], "tooth": 99}], {}, None),
        (ITEMS, {"total_cents": 1}, None),
        ([{**ITEMS[0], "quantity": 2, "unit_price_cents": 2**62}], {}, "amount_too_large"),
    ],
    ids=["fases", "cero", "51", "fase11", "neg", "decimal", "cant0", "pieza", "total", "overflow"],
)
async def test_validaciones_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    scene: ClinicScene,
    items: list[dict[str, Any]],
    extra: dict[str, Any],
    detalle: str | None,
) -> None:
    rid = await open_record(app_client, scene)

    respuesta = await _plan(app_client, scene, rid, items, **extra)

    assert respuesta.status_code == 422
    if detalle:
        assert respuesta.json() == {"detail": detalle}
    assert await count_rows(db_session, TreatmentPlanVersion) == 0


async def test_versiones_decision_y_listado(
    app_client: httpx.AsyncClient, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)
    plan = (await _plan(app_client, scene, rid, ITEMS)).json()
    base = f"/api/clinical-records/{rid}/treatment-plans/{plan['id']}"
    h = scene.headers["odontologo"]

    v2 = await app_client.post(
        f"{base}/versions",
        json={"expected_version": 1, "items": [{**ITEMS[0], "unit_price_cents": 20000}]},
        headers=h,
    )
    vieja = await app_client.post(
        f"{base}/versions", json={"expected_version": 1, "items": ITEMS}, headers=h
    )
    sobre_v1 = await app_client.post(
        f"{base}/versions/1/decision", json={"decision": "accepted"}, headers=h
    )
    invalida = await app_client.post(
        f"{base}/versions/2/decision", json={"decision": "pending"}, headers=h
    )
    aceptada = await app_client.post(
        f"{base}/versions/2/decision", json={"decision": "accepted"}, headers=h
    )
    doble = await app_client.post(
        f"{base}/versions/2/decision", json={"decision": "rejected"}, headers=h
    )
    listado = (
        await app_client.get(f"/api/clinical-records/{rid}/treatment-plans", headers=h)
    ).json()

    assert v2.status_code == 201
    versiones = v2.json()["versions"]
    assert [v["total_cents"] for v in versiones] == [115000, 40000]
    assert (vieja.status_code, vieja.json()) == (409, {"detail": "version_conflict"})
    assert (sobre_v1.status_code, sobre_v1.json()) == (409, {"detail": "version_superseded"})
    assert invalida.status_code == 422
    assert aceptada.status_code == 201
    assert aceptada.json()["versions"][1]["decision"]["decision"] == "accepted"
    assert (doble.status_code, doble.json()) == (409, {"detail": "version_already_decided"})
    assert listado["items"][0]["latest_version"] == 2
    assert (listado["items"][0]["total_cents"], listado["items"][0]["decision"]) == (
        40000,
        "accepted",
    )


async def test_plan_de_otra_ficha_es_404(app_client: httpx.AsyncClient, scene: ClinicScene) -> None:
    rid = await open_record(app_client, scene)
    rid_b = (
        await app_client.post(
            f"/api/patients/{scene.patient_b.id}/clinical-record",
            headers=scene.headers["admin_prof"],
        )
    ).json()["record_id"]
    ajeno = (
        await app_client.post(
            f"/api/clinical-records/{rid_b}/treatment-plans",
            json={"title": "Plan ajeno", "items": ITEMS},
            headers=scene.headers["admin_prof"],
        )
    ).json()

    respuesta = await app_client.get(
        f"/api/clinical-records/{rid}/treatment-plans/{ajeno['id']}",
        headers=scene.headers["odontologo"],
    )

    assert (respuesta.status_code, respuesta.json()) == (404, {"detail": "plan_not_found"})


async def test_decisiones_paralelas(committed_engine: AsyncEngine) -> None:
    async with AsyncSession(committed_engine, expire_on_commit=False) as session:
        s = await make_committed_scene(session)
    principal = principal_of(s.dentist)
    async with AsyncSession(committed_engine, expire_on_commit=False) as session:
        ficha = await RecordService(session, principal).open(s.patient_id)
        plan = await PlanService(session, principal).create(
            ficha.record_id,
            PlanCreate(
                title="Plan ficticio",
                items=[
                    PlanItemIn(phase=1, description="Item ficticio", quantity=1, unit_price_cents=1)
                ],
            ),
        )

    async def _decidir(valor: str) -> int:
        async with AsyncSession(committed_engine, expire_on_commit=False) as session:
            try:
                await PlanService(session, principal).decide(
                    ficha.record_id, plan.id, 1, DecisionCreate(decision=valor)  # type: ignore[arg-type]
                )
            except DomainError as exc:
                return exc.status_code
            return 201

    assert sorted(await asyncio.gather(_decidir("accepted"), _decidir("rejected"))) == [201, 409]
    async with AsyncSession(committed_engine) as session:
        assert await session.scalar(select(func.count()).select_from(TreatmentPlanDecision)) == 1


async def test_pdf_valido_sin_datos_sensibles_y_auditado(
    app_client: httpx.AsyncClient,
    app_instance: FastAPI,
    db_session: AsyncSession,
    scene: ClinicScene,
) -> None:
    from app.common.clock import get_now

    await db_session.execute(
        update(Patient)
        .where(Patient.id == scene.patient.id)
        .values(full_name="Ñandú Pérez Ficticio")
    )
    # 02:30 UTC del 11/11 = 23:30 del 10/11 en Buenos Aires (RN-GL-03).
    app_instance.dependency_overrides[get_now] = lambda: datetime(2026, 11, 11, 2, 30, tzinfo=UTC)
    rid = await open_record(app_client, scene)
    plan = (await _plan(app_client, scene, rid, ITEMS)).json()
    base = f"/api/clinical-records/{rid}/treatment-plans/{plan['id']}/versions"

    respuesta = await app_client.get(f"{base}/1/pdf", headers=scene.headers["odontologo"])
    inexistente = await app_client.get(f"{base}/9/pdf", headers=scene.headers["odontologo"])

    assert respuesta.status_code == 200
    assert respuesta.content.startswith(b"%PDF-")
    assert respuesta.headers["content-type"] == "application/pdf"
    assert respuesta.headers["content-disposition"].startswith("attachment")
    assert respuesta.headers["cache-control"] == "no-store"
    texto = "".join(p.extract_text() for p in PdfReader(io.BytesIO(respuesta.content)).pages)
    assert "1.150,00" in texto
    assert "Fase 1" in texto and "Fase 2" in texto
    assert "10/11/2026" in texto
    assert "Ñandú Pérez Ficticio" in texto and "Cóndilo/Ø" in texto
    assert DNI_FICTICIO not in texto
    assert (scene.patient.phone_e164 or "+54")[-8:] not in texto
    assert inexistente.status_code == 404
    evento = (await access_events(db_session, action=ClinicalAction.PLAN_PDF_EXPORT))[0]
    assert (str(evento.object_id), evento.payload) == (plan["id"], {"version": 1})
