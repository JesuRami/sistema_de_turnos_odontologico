"""Carrera directa en la base (C-05 tarea 1.4): dos conexiones, mismo hueco, sin servicio.

La segunda inserción espera el lock del índice gist y, al confirmar la primera,
falla con SQLSTATE `23P01` (exclusion_violation). Commits reales en DB temporal.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.factories import make_chair, make_clinic, make_patient, make_professional, make_user

pytestmark = pytest.mark.integration

_INSERT = text(
    """
    INSERT INTO appointment (clinic_id, patient_id, professional_id, chair_id, starts_at,
                             ends_at, occupied_until, status, origin, created_by_user_id)
    VALUES (:clinic_id, :patient_id, :professional_id, :chair_id, :starts_at, :ends_at,
            :ends_at, 'confirmed', 'reception', :user_id)
    """
)


async def _datos(engine: AsyncEngine) -> dict[str, Any]:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        clinic = await make_clinic(session)
        valores = {
            "clinic_id": clinic.id,
            "patient_id": (await make_patient(session, clinic)).id,
            "professional_id": (await make_professional(session, clinic)).id,
            "chair_id": (await make_chair(session, clinic)).id,
            "user_id": (await make_user(session, clinic)).id,
            "starts_at": datetime(2030, 1, 7, 13, 0, tzinfo=UTC),
            "ends_at": datetime(2030, 1, 7, 13, 30, tzinfo=UTC),
        }
        await session.commit()
    return valores


async def test_dos_conexiones_mismo_hueco_una_falla_con_23P01(
    committed_engine: AsyncEngine,
) -> None:
    valores = await _datos(committed_engine)
    async with committed_engine.connect() as primera, committed_engine.connect() as segunda:
        await primera.begin()
        await primera.execute(_INSERT, valores)

        await segunda.begin()
        espera = asyncio.create_task(segunda.execute(_INSERT, valores))
        await asyncio.sleep(0.3)
        assert not espera.done(), "la segunda inserción debe esperar a la primera"
        await primera.commit()

        with pytest.raises(IntegrityError) as exc:
            await espera
        orig = exc.value.orig
        assert (getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)) == "23P01"
        await segunda.rollback()

    async with committed_engine.connect() as conn:
        total = await conn.scalar(text("SELECT count(*) FROM appointment"))
    assert total == 1
