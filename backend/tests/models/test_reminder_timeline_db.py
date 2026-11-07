"""Invariantes de base del timeline de recordatorios (C-11, D1; reglas 4, 7, 9 y 11).

Postgres real: el append-only de `reminder_manual_resend`, sus FKs compuestas intra-tenant, el
largo de la nota, la columna `reminder_job.manual_resend_at` y el índice parcial de fallidos los
impone la base, no la aplicación. Datos ficticios (regla 13).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.models import (
    Appointment,
    Clinic,
    ReminderChannel,
    ReminderJob,
    ReminderManualResend,
    ReminderStatus,
    User,
    UserRole,
)
from sqlalchemy import delete, select, text, update
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

AHORA = datetime(2030, 1, 7, 8, 0, tzinfo=UTC)
INICIO = AHORA + timedelta(days=5)


@dataclass(frozen=True, slots=True)
class Tenant:
    clinic: Clinic
    appointment: Appointment
    job: ReminderJob
    user: User


async def _tenant(session: AsyncSession) -> Tenant:
    clinic = await make_clinic(session)
    patient = await make_patient(session, clinic)
    professional = await make_professional(session, clinic)
    chair = await make_chair(session, clinic)
    appointment = await make_appointment(
        session, clinic, patient=patient, professional=professional, chair=chair, starts_at=INICIO
    )
    job = ReminderJob(
        clinic_id=clinic.id,
        appointment_id=appointment.id,
        step="t_24h",
        channel=ReminderChannel.WHATSAPP,
        scheduled_for=INICIO - timedelta(hours=24),
        available_at=INICIO - timedelta(hours=24),
        starts_at_snapshot=INICIO,
        status=ReminderStatus.FAILED,
    )
    session.add(job)
    user = await make_user(session, clinic, role=UserRole.RECEPCION)
    await session.flush()
    return Tenant(clinic, appointment, job, user)


def _resend(t: Tenant, **overrides: Any) -> ReminderManualResend:
    values: dict[str, Any] = {
        "clinic_id": t.clinic.id,
        "appointment_id": t.appointment.id,
        "reminder_job_id": t.job.id,
        "actor_user_id": t.user.id,
    }
    values.update(overrides)
    return ReminderManualResend(**values)


async def _flush_falla(session: AsyncSession, *objetos: object, match: str) -> None:
    with pytest.raises((IntegrityError, DBAPIError), match=match):
        async with session.begin_nested():
            session.add_all(objetos)
            await session.flush()


async def test_reenvio_se_guarda_con_nota_opcional(db_session: AsyncSession) -> None:
    t = await _tenant(db_session)
    sin_nota = _resend(t)
    db_session.add(sin_nota)
    await db_session.flush()

    assert sin_nota.note is None
    assert sin_nota.created_at is not None


async def test_reenvio_es_append_only(db_session: AsyncSession) -> None:
    t = await _tenant(db_session)
    fila = _resend(t, note="Paciente pidió que se reenvíe")
    db_session.add(fila)
    await db_session.flush()

    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(
                update(ReminderManualResend)
                .where(ReminderManualResend.id == fila.id)
                .values(note="otra")
            )
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(
                delete(ReminderManualResend).where(ReminderManualResend.id == fila.id)
            )


@pytest.mark.parametrize("campo", ["appointment_id", "reminder_job_id", "actor_user_id"])
async def test_referencias_de_otra_clinica_se_rechazan(
    db_session: AsyncSession, campo: str
) -> None:
    a = await _tenant(db_session)
    b = await _tenant(db_session)
    ajeno = {
        "appointment_id": b.appointment.id,
        "reminder_job_id": b.job.id,
        "actor_user_id": b.user.id,
    }[campo]

    await _flush_falla(db_session, _resend(a, **{campo: ajeno}), match="fk_reminder_manual_resend")


async def test_nota_de_200_caracteres_se_admite_y_de_201_no(db_session: AsyncSession) -> None:
    t = await _tenant(db_session)
    db_session.add(_resend(t, note="x" * 200))
    await db_session.flush()

    await _flush_falla(db_session, _resend(t, note="x" * 201), match="note_length")


async def test_marca_de_reenvio_manual_del_job(db_session: AsyncSession) -> None:
    t = await _tenant(db_session)
    assert t.job.manual_resend_at is None

    t.job.manual_resend_at = AHORA
    await db_session.flush()
    releido = await db_session.scalar(
        select(ReminderJob.manual_resend_at).where(ReminderJob.id == t.job.id)
    )

    assert releido == AHORA


async def test_indice_parcial_de_fallidos_existe(db_session: AsyncSession) -> None:
    definicion = await db_session.scalar(
        text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_reminder_job_failed'")
    )

    assert definicion is not None
    assert "(clinic_id, scheduled_for)" in definicion
    assert "status = 'failed'" in definicion
