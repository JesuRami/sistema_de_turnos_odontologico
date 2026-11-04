"""Instantánea de `appointment_event`: coherencia, tenant y auditoría intacta (C-13, S4)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.models import ActorType, AppointmentEvent, AppointmentEventType, AppointmentStatus
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import (
    make_appointment,
    make_chair,
    make_clinic,
    make_patient,
    make_professional,
    make_user,
)

pytestmark = pytest.mark.integration

INICIO = datetime(2030, 1, 7, 13, 0, tzinfo=UTC)


async def _evento(db_session: AsyncSession, **overrides: object) -> AppointmentEvent:
    clinic = await make_clinic(db_session)
    profesional = await make_professional(db_session, clinic)
    sillon = await make_chair(db_session, clinic)
    turno = await make_appointment(
        db_session,
        clinic,
        patient=await make_patient(db_session, clinic),
        professional=profesional,
        chair=sillon,
        starts_at=INICIO,
    )
    valores: dict[str, object] = {
        "clinic_id": clinic.id,
        "appointment_id": turno.id,
        "actor_type": ActorType.USER,
        "actor_user_id": (await make_user(db_session, clinic)).id,
        "event": AppointmentEventType.CREATED,
        "to_status": AppointmentStatus.CONFIRMED,
        "payload": {},
        "slot_starts_at": INICIO,
        "slot_ends_at": INICIO + timedelta(minutes=30),
        "professional_id": profesional.id,
        "chair_id": sillon.id,
    }
    valores.update(overrides)
    evento = AppointmentEvent(**valores)
    db_session.add(evento)
    await db_session.flush()
    return evento


async def test_evento_con_instantanea_completa_es_valido(db_session: AsyncSession) -> None:
    evento = await _evento(db_session)
    assert evento.slot_starts_at == INICIO


async def test_evento_sin_instantanea_sigue_siendo_valido(db_session: AsyncSession) -> None:
    evento = await _evento(
        db_session, slot_starts_at=None, slot_ends_at=None, professional_id=None, chair_id=None
    )
    assert evento.slot_starts_at is None


async def test_instantanea_parcial_o_invertida_se_rechaza(db_session: AsyncSession) -> None:
    with pytest.raises(IntegrityError, match="ck_appointment_event_slot_coherent"):
        async with db_session.begin_nested():
            await _evento(db_session, chair_id=None)
    with pytest.raises(IntegrityError, match="ck_appointment_event_slot_coherent"):
        async with db_session.begin_nested():
            await _evento(db_session, slot_ends_at=INICIO - timedelta(minutes=5))


async def test_profesional_de_otra_clinica_viola_la_fk(db_session: AsyncSession) -> None:
    ajena = await make_professional(db_session, await make_clinic(db_session))
    with pytest.raises(
        IntegrityError, match="fk_appointment_event_clinic_id_professional_id_professional"
    ):
        async with db_session.begin_nested():
            await _evento(db_session, professional_id=ajena.id)


async def test_el_evento_con_instantanea_sigue_siendo_inmutable(db_session: AsyncSession) -> None:
    evento = await _evento(db_session)
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE appointment_event SET slot_starts_at = NULL WHERE id = :id"),
                {"id": evento.id},
            )
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(
                text("DELETE FROM appointment_event WHERE id = :id"), {"id": evento.id}
            )
