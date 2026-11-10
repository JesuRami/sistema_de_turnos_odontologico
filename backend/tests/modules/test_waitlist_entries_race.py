"""Carrera de dos altas de la misma entrada con commits reales (C-12; spec waitlist/entries).

Dos sesiones independientes, como dos requests en producción: una crea la entrada y la otra
recibe `409 already_waiting` por el índice único parcial. Datos ficticios (regla 13).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import pytest
from app.common.exceptions import DomainError
from app.core.settings import Settings
from app.models import ActorType, UserRole, WaitingListEntry
from app.modules.appointments.audit import Actor
from app.modules.waiting_list.entries import EntriesService
from app.modules.waiting_list.schemas import EntryCreate
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.factories import make_clinic, make_patient, make_user

pytestmark = pytest.mark.integration

AHORA = datetime(2030, 1, 7, 11, 0, tzinfo=UTC)


async def test_dos_altas_simultaneas(committed_engine: AsyncEngine, settings: Settings) -> None:
    async with AsyncSession(committed_engine, expire_on_commit=False) as s:
        clinic = await make_clinic(s)
        paciente = await make_patient(s, clinic)
        user = await make_user(s, clinic, role=UserRole.RECEPCION)
        await s.commit()
    actor = Actor(
        clinic_id=clinic.id,
        type=ActorType.USER,
        user_id=user.id,
        roles=frozenset({UserRole.RECEPCION}),
    )
    payload = EntryCreate(
        patient_id=paciente.id,
        professional_id=None,
        date_from=date(2030, 1, 8),
        date_to=date(2030, 1, 20),
    )

    async def _alta() -> str:
        async with AsyncSession(committed_engine, expire_on_commit=False) as s:
            try:
                await EntriesService(s, actor, AHORA, settings).create(payload)
            except DomainError as error:
                return error.detail
            return "created"

    resultados = await asyncio.gather(_alta(), _alta())

    assert sorted(resultados) == ["already_waiting", "created"]
    async with AsyncSession(committed_engine) as s:
        total = await s.scalar(
            select(func.count())
            .select_from(WaitingListEntry)
            .where(WaitingListEntry.patient_id == paciente.id)
        )
    assert total == 1
