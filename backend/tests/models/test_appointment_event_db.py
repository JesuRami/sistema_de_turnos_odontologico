"""`appointment_event` es append-only (trigger) y coherente con su actor (C-05, RN-GL-01)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.models import (
    ActorType,
    AppointmentEvent,
    AppointmentEventType,
    AppointmentStatus,
)
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


async def _evento(db_session: AsyncSession, **overrides: object) -> AppointmentEvent:
    clinic = await make_clinic(db_session)
    appointment = await make_appointment(
        db_session,
        clinic,
        patient=await make_patient(db_session, clinic),
        professional=await make_professional(db_session, clinic),
        chair=await make_chair(db_session, clinic),
        starts_at=datetime(2030, 1, 7, 13, 0, tzinfo=UTC),
    )
    valores: dict[str, object] = {
        "clinic_id": clinic.id,
        "appointment_id": appointment.id,
        "actor_type": ActorType.USER,
        "actor_user_id": (await make_user(db_session, clinic)).id,
        "event": AppointmentEventType.CREATED,
        "to_status": AppointmentStatus.CONFIRMED,
        "payload": {"origin": "reception"},
    }
    valores.update(overrides)
    evento = AppointmentEvent(**valores)
    db_session.add(evento)
    await db_session.flush()
    return evento


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE appointment_event SET payload = '{}'::jsonb WHERE id = :id",
        "DELETE FROM appointment_event WHERE id = :id",
    ],
)
async def test_evento_rechaza_update_y_delete(db_session: AsyncSession, sql: str) -> None:
    evento = await _evento(db_session)
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(text(sql), {"id": evento.id})


async def test_actor_user_exige_actor_user_id(db_session: AsyncSession) -> None:
    with pytest.raises(IntegrityError, match="ck_appointment_event_actor_user_coherent"):
        async with db_session.begin_nested():
            await _evento(db_session, actor_user_id=None)


async def test_actor_system_sin_usuario_es_valido(db_session: AsyncSession) -> None:
    evento = await _evento(db_session, actor_type=ActorType.SYSTEM, actor_user_id=None)
    assert evento.created_at is not None


async def test_payload_debe_ser_objeto(db_session: AsyncSession) -> None:
    with pytest.raises(IntegrityError, match="ck_appointment_event_payload_is_object"):
        async with db_session.begin_nested():
            await _evento(db_session, payload=["no", "objeto"])


async def test_evento_de_turno_de_otra_clinica_viola_la_fk(db_session: AsyncSession) -> None:
    otra = await make_clinic(db_session)
    with pytest.raises(IntegrityError, match="fk_appointment_event_clinic_id_appointment_id"):
        async with db_session.begin_nested():
            await _evento(
                db_session, clinic_id=otra.id, actor_type=ActorType.SYSTEM, actor_user_id=None
            )
