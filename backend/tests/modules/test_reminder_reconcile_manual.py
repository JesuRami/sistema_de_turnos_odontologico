"""Un reenvío manual pendiente frente a `reconcile` y al despacho (C-11, D5; spec job-scheduling).

Postgres real. El job reenviado queda `scheduled` con su `scheduled_for` original (ya vencido) y
`manual_resend_at` no nulo: el recálculo no debe cancelarlo por `STEP_ELAPSED` salvo que el turno
se mueva, se cancele o el paso deje de estar configurado. Datos ficticios (regla 13).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from app.core.settings import Settings
from app.models import (
    AppointmentStatus,
    CancellationReason,
    Clinic,
    DeliveryEventType,
    ReminderChannel,
    ReminderJob,
    ReminderReason,
    ReminderStatus,
)
from app.modules.reminders.dispatch import run_tick
from app.modules.reminders.scheduling import reconcile
from app.modules.reminders.senders.base import SendError
from app.modules.reminders.senders.fake import FakeSender
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.reminder_helpers import (
    AHORA,
    Scene,
    W,
    commit_job,
    commit_scene,
    dispatch_settings,
    jobs_of,
    make_job,
    make_scene,
    read_events,
    read_jobs,
)

pytestmark = pytest.mark.integration

# Turno a 10 h: el paso de 24 h ya pasó; recepción lo reenvió hace un minuto.
REENVIO = AHORA - timedelta(minutes=1)


async def _reenviado(session: AsyncSession, escena: Scene) -> ReminderJob:
    return await make_job(
        session,
        escena.appointment,
        step="t_24h",
        status=ReminderStatus.SCHEDULED,
        available_at=REENVIO,
        manual_resend_at=REENVIO,
    )


async def _mover(session: AsyncSession, escena: Scene, horas: float) -> None:
    turno = escena.appointment
    turno.starts_at = AHORA + timedelta(hours=horas)
    turno.ends_at = turno.starts_at + timedelta(minutes=30)
    turno.occupied_until = turno.ends_at
    await session.flush()


async def _job(session: AsyncSession, escena: Scene) -> ReminderJob:
    return (await jobs_of(session, escena.appointment.id))[("t_24h", "whatsapp")]


async def test_mutacion_no_relacionada_no_cancela_el_reenvio(db_session: AsyncSession) -> None:
    escena = await make_scene(db_session, starts_in=timedelta(hours=10))
    await _reenviado(db_session, escena)

    await reconcile(db_session, escena.appointment, now=AHORA)

    job = await _job(db_session, escena)
    assert job.status is ReminderStatus.SCHEDULED
    assert job.manual_resend_at == REENVIO
    assert job.available_at == REENVIO


async def test_reprogramar_a_una_semana_recalcula_y_limpia_la_marca(
    db_session: AsyncSession,
) -> None:
    escena = await make_scene(db_session, starts_in=timedelta(hours=10))
    await _reenviado(db_session, escena)
    await _mover(db_session, escena, horas=24 * 7)

    await reconcile(db_session, escena.appointment, now=AHORA)

    job = await _job(db_session, escena)
    nuevo = escena.appointment.starts_at
    assert job.status is ReminderStatus.SCHEDULED
    assert job.scheduled_for == nuevo - timedelta(hours=24)
    assert job.available_at == job.scheduled_for
    assert job.starts_at_snapshot == nuevo
    assert job.manual_resend_at is None


async def test_reprogramar_con_el_paso_vencido_cancela(db_session: AsyncSession) -> None:
    escena = await make_scene(db_session, starts_in=timedelta(hours=10))
    await _reenviado(db_session, escena)
    await _mover(db_session, escena, horas=2)

    await reconcile(db_session, escena.appointment, now=AHORA)

    job = await _job(db_session, escena)
    assert job.status is ReminderStatus.CANCELLED
    assert job.reason == ReminderReason.STEP_ELAPSED.value
    assert job.manual_resend_at is None


async def test_quitar_el_paso_de_la_clinica_cancela(db_session: AsyncSession) -> None:
    escena = await make_scene(db_session, starts_in=timedelta(hours=10))
    await _reenviado(db_session, escena)
    await db_session.execute(
        update(Clinic)
        .where(Clinic.id == escena.clinic.id)
        .values(reminder_steps=[{"offset_h": 3, "channel": "whatsapp"}])
    )

    await reconcile(db_session, escena.appointment, now=AHORA)

    job = await _job(db_session, escena)
    assert job.status is ReminderStatus.CANCELLED
    assert job.reason == ReminderReason.STEP_REMOVED.value
    assert job.manual_resend_at is None


async def test_cancelar_el_turno_cancela_el_reenvio(db_session: AsyncSession) -> None:
    escena = await make_scene(db_session, starts_in=timedelta(hours=10))
    await _reenviado(db_session, escena)
    turno = escena.appointment
    turno.status = AppointmentStatus.CANCELLED
    turno.cancelled_at = AHORA
    turno.cancellation_reason = CancellationReason.PACIENTE
    await db_session.flush()

    await reconcile(db_session, turno, now=AHORA)

    job = await _job(db_session, escena)
    assert job.status is ReminderStatus.CANCELLED
    assert job.reason == ReminderReason.APPOINTMENT_INACTIVE.value
    assert job.manual_resend_at is None


# ------------------------------------------------------------------ despacho (commits reales)


def _senders() -> dict[ReminderChannel, FakeSender]:
    return {
        ReminderChannel.WHATSAPP: FakeSender(ReminderChannel.WHATSAPP),
        ReminderChannel.EMAIL: FakeSender(ReminderChannel.EMAIL),
    }


async def test_al_enviarse_limpia_la_marca_y_registra_el_reenvio(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True, starts_in=timedelta(hours=10))
    job = await commit_job(
        rem_maker,
        escena.appointment,
        step="t_24h",
        available_at=REENVIO,
        manual_resend_at=REENVIO,
    )
    senders = _senders()

    await run_tick(rem_maker, senders, dispatch_settings(settings), now=lambda: AHORA)

    enviado = (await read_jobs(rem_maker, escena.appointment.id))[("t_24h", "whatsapp")]
    assert enviado.status is ReminderStatus.SENT
    assert enviado.manual_resend_at is None
    [sent] = [e for e in await read_events(rem_maker, job.id) if e.event_type is W_SENT]
    assert sent.payload.get("manual") is True


async def test_al_fallar_definitivamente_limpia_la_marca(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True, starts_in=timedelta(hours=10))
    await commit_job(
        rem_maker,
        escena.appointment,
        step="t_24h",
        available_at=REENVIO,
        manual_resend_at=REENVIO,
    )
    senders = _senders()
    senders[ReminderChannel.WHATSAPP].failures.append(SendError("meta_131026", retryable=False))

    await run_tick(rem_maker, senders, dispatch_settings(settings), now=lambda: AHORA)

    fallido = (await read_jobs(rem_maker, escena.appointment.id))[("t_24h", "whatsapp")]
    assert fallido.status is ReminderStatus.FAILED
    assert fallido.manual_resend_at is None


async def test_al_saltarse_por_consentimiento_limpia_la_marca(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=False, starts_in=timedelta(hours=10))
    await commit_job(
        rem_maker,
        escena.appointment,
        step="t_24h",
        available_at=REENVIO,
        manual_resend_at=REENVIO,
    )

    await run_tick(rem_maker, _senders(), dispatch_settings(settings), now=lambda: AHORA)

    saltado = (await read_jobs(rem_maker, escena.appointment.id))[("t_24h", "whatsapp")]
    assert saltado.status is ReminderStatus.SKIPPED
    assert saltado.manual_resend_at is None


W_SENT = DeliveryEventType.SENT
_ = W
