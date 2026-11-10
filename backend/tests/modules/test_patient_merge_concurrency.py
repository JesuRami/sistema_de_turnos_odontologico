"""Carrera fusión vs. alta de turno del duplicado (C-06 tarea 3.3, D9).

Commits reales en DB temporal. La fusión toma `FOR UPDATE` sobre los pacientes;
el alta de turno lee al paciente con `FOR SHARE`, así que espera y, al ver al
duplicado ya fusionado, responde `422 invalid_patient`. Sin ese lock, el alta
leería la versión vieja (MVCC) y dejaría un turno colgado del duplicado.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest
from app.common.exceptions import DomainError
from app.models import ActorType, Appointment, AppointmentOrigin, UserRole
from app.modules.appointments.audit import Actor
from app.modules.appointments.service import AppointmentsService, Booking
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.factories import (
    make_chair,
    make_clinic,
    make_patient,
    make_professional,
    make_schedule_rule,
    make_user,
)

pytestmark = pytest.mark.integration

BA = ZoneInfo("America/Argentina/Buenos_Aires")
AHORA = datetime(2030, 1, 7, 8, 0, tzinfo=BA)


async def test_alta_espera_a_la_fusion_y_rechaza_al_duplicado(
    committed_engine: AsyncEngine,
) -> None:
    async with AsyncSession(committed_engine, expire_on_commit=False) as session:
        clinic = await make_clinic(session)
        professional = await make_professional(session, clinic)
        chair = await make_chair(session, clinic)
        await make_schedule_rule(session, clinic, professional, chair, start_time=time(9))
        user = await make_user(session, clinic, role=UserRole.RECEPCION)
        conservado = await make_patient(session, clinic)
        duplicado = await make_patient(session, clinic)
        await session.commit()
    actor = Actor(
        clinic_id=clinic.id,
        type=ActorType.USER,
        user_id=user.id,
        roles=frozenset({UserRole.RECEPCION}),
    )

    async def _reservar() -> uuid.UUID:
        async with AsyncSession(committed_engine) as session:
            turno = await AppointmentsService(session, actor, AHORA).book(
                Booking(
                    patient_id=duplicado.id,
                    professional_id=professional.id,
                    chair_id=chair.id,
                    starts_at=datetime(2030, 1, 7, 10, 0, tzinfo=BA),
                    duration_min=None,
                ),
                origin=AppointmentOrigin.RECEPTION,
            )
            await session.commit()
            return turno.id

    async with committed_engine.connect() as fusion:
        await fusion.begin()
        await fusion.execute(
            text("SELECT id FROM patient WHERE id IN (:a, :b) ORDER BY id FOR UPDATE"),
            {"a": conservado.id, "b": duplicado.id},
        )
        alta = asyncio.create_task(_reservar())
        await asyncio.sleep(0.3)
        assert not alta.done(), "el alta debe esperar el lock de la fusión"
        await fusion.execute(
            text(
                "UPDATE patient SET archived_at = now(), merged_into_patient_id = :c WHERE id = :d"
            ),
            {"c": conservado.id, "d": duplicado.id},
        )
        await fusion.commit()

    with pytest.raises(DomainError) as exc:
        await alta
    assert (exc.value.status_code, exc.value.detail) == (422, "invalid_patient")
    async with AsyncSession(committed_engine) as session:
        colgados = await session.scalar(
            select(func.count()).where(Appointment.patient_id == duplicado.id)
        )
    assert colgados == 0
