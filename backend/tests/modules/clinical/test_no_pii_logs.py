"""Logs sin contenido clínico ni PII (C-15, D12; escenarios "Logs sin contenido clínico" y
"Error de validación sin eco")."""

from __future__ import annotations

import logging

import httpx
import pytest
from app.core.settings import Settings
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tests.clinical_helpers import (
    DNI_FICTICIO,
    NOMBRE_PACIENTE,
    TEXTO_CLINICO,
    make_clinic_scene,
    open_record,
    seed_catalog,
)

pytestmark = pytest.mark.integration

ITEM = {"phase": 1, "description": "Item ficticio", "quantity": 1, "unit_price_cents": 100}


async def test_operaciones_clinicas_no_loguean_datos_sensibles(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    s = await make_clinic_scene(db_session, redis_client, settings)
    await seed_catalog(db_session, s.clinic)
    h = s.headers["odontologo"]
    with caplog.at_level(logging.DEBUG):
        rid = await open_record(app_client, s)
        base = f"/api/clinical-records/{rid}"
        await app_client.get(f"/api/patients/{s.patient.id}/clinical-record", headers=h)
        await app_client.post(
            f"{base}/anamnesis",
            json={"expected_version": 0, "answers": {"observations": TEXTO_CLINICO}},
            headers=h,
        )
        await app_client.post(f"{base}/evolutions", json={"body": TEXTO_CLINICO}, headers=h)
        invalida = await app_client.post(
            f"{base}/evolutions", json={"body": TEXTO_CLINICO, "x": TEXTO_CLINICO}, headers=h
        )
        await app_client.post(
            f"{base}/odontogram/events",
            json={"entries": [{"tooth": 36, "surface": "O", "note": TEXTO_CLINICO}]},
            headers=h,
        )
        plan = await app_client.post(
            f"{base}/treatment-plans",
            json={"title": TEXTO_CLINICO[:100], "items": [ITEM]},
            headers=h,
        )
        await app_client.get(
            f"{base}/treatment-plans/{plan.json()['id']}/versions/1/pdf", headers=h
        )

    assert invalida.status_code == 422
    assert TEXTO_CLINICO not in invalida.text
    for registro in caplog.records:
        mensaje = registro.getMessage()
        for sensible in (TEXTO_CLINICO, NOMBRE_PACIENTE, DNI_FICTICIO):
            assert sensible not in mensaje
