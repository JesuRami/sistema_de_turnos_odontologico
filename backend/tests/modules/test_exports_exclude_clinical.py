"""Las exportaciones no incluyen datos clínicos (C-15, D9, spec `core/data-export`, Decisión 11)."""

from __future__ import annotations

import io
import zipfile

import httpx
import pytest
from app.core.settings import Settings
from app.models import Base
from app.modules.reports.exports import CLINICAL_TABLES, EXCLUDED_FROM_EXPORT, TABLES
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tests.clinical_helpers import TEXTO_CLINICO, make_clinic_scene, open_record

pytestmark = pytest.mark.integration

ANAMNESIS_FICTICIA = "Alergia sintética exportable"


async def test_exportaciones_sin_cadenas_ni_claves_clinicas(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    s = await make_clinic_scene(db_session, redis_client, settings)
    rid = await open_record(app_client, s)
    h = s.headers["odontologo"]
    await app_client.post(
        f"/api/clinical-records/{rid}/anamnesis",
        json={"expected_version": 0, "answers": {"allergies": [ANAMNESIS_FICTICIA]}},
        headers=h,
    )
    await app_client.post(
        f"/api/clinical-records/{rid}/evolutions", json={"body": TEXTO_CLINICO}, headers=h
    )

    completa = await app_client.get(
        "/api/exports/full", params={"format": "json"}, headers=s.headers["admin"]
    )
    paciente = await app_client.get(
        f"/api/exports/patients/{s.patient.id}", headers=s.headers["admin"]
    )

    assert completa.status_code == 200 and paciente.status_code == 200
    archivo = zipfile.ZipFile(io.BytesIO(completa.content))
    contenido = "".join(archivo.read(n).decode("utf-8", "replace") for n in archivo.namelist())
    textos = [contenido, paciente.text]
    for texto in textos:
        assert TEXTO_CLINICO not in texto
        assert ANAMNESIS_FICTICIA not in texto
        assert str(rid) not in texto
        for clave in ("clinical_record", "anamnesis", "evolution", "odontogram"):
            assert clave not in texto


def test_toda_tabla_con_clinic_id_esta_clasificada() -> None:
    """Una tabla nueva sin clasificar (ni exportada ni excluida) rompe esta prueba."""
    con_clinica = {t.name for t in Base.metadata.sorted_tables if "clinic_id" in t.c}
    exportadas = {t.model.__tablename__ for t in TABLES}

    assert con_clinica - exportadas - set(EXCLUDED_FROM_EXPORT) == set()
    assert exportadas.isdisjoint(EXCLUDED_FROM_EXPORT)
    assert set(CLINICAL_TABLES) <= set(EXCLUDED_FROM_EXPORT)
    assert len(CLINICAL_TABLES) == 12
