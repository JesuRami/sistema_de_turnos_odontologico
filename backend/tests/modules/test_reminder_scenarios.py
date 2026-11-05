"""Los tres escenarios que exige CHANGES.md para C-09 (tarea 8.7).

Caída del worker (los jobs sobreviven), doble tick (no duplica) y opt-out a mitad de secuencia.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest
from app.core.settings import Settings
from app.models import (
    Appointment,
    AppointmentStatus,
    CancellationReason,
    ConsentSource,
    ConsentStatus,
    ReminderChannel,
)
from app.modules.reminders.consent import ConsentService
from app.modules.reminders.dispatch import run_tick
from app.modules.reminders.scheduling import schedule_new
from app.modules.reminders.senders.fake import FakeSender
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.conftest import MutableClock
from tests.reminder_helpers import (
    AHORA,
    commit_job,
    commit_scene,
    dispatch_settings,
    read_jobs,
)

pytestmark = pytest.mark.integration

W = ReminderChannel.WHATSAPP


def _estados(jobs: dict[tuple[str, str], Any]) -> dict[str, str]:
    return {f"{paso}/{canal}": job.status.value for (paso, canal), job in jobs.items()}


async def test_caida_del_worker_los_jobs_sobreviven_y_se_resuelven_al_volver(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    futuro = await commit_scene(rem_maker, opt_in=True)
    iniciado = await commit_scene(rem_maker, opt_in=True, starts_in=timedelta(minutes=-10))
    cancelado = await commit_scene(rem_maker, opt_in=True)
    # Los tres vencieron mientras el worker estaba detenido (hace 2 horas).
    for escena in (futuro, iniciado, cancelado):
        await commit_job(rem_maker, escena.appointment, scheduled_for=AHORA - timedelta(hours=2))
    async with rem_maker() as session:
        await session.execute(
            update(Appointment)
            .where(Appointment.id == cancelado.appointment.id)
            .values(
                status=AppointmentStatus.CANCELLED,
                cancelled_at=AHORA,
                cancellation_reason=CancellationReason.PACIENTE,
            )
        )
        await session.commit()
    sender = FakeSender(W)

    # "Vuelve el worker": el primer tick procesa lo vencido.
    await run_tick(rem_maker, {W: sender}, dispatch_settings(settings), now=lambda: AHORA)

    assert _estados(await read_jobs(rem_maker, futuro.appointment.id)) == {"t_24h/whatsapp": "sent"}
    assert _estados(await read_jobs(rem_maker, iniciado.appointment.id)) == {
        "t_24h/whatsapp": "skipped"
    }
    assert _estados(await read_jobs(rem_maker, cancelado.appointment.id)) == {
        "t_24h/whatsapp": "cancelled"
    }
    assert len(sender.sent) == 1


async def test_doble_tick_no_duplica_ninguna_secuencia(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True)
    for paso in ("created", "t_72h", "t_24h"):
        await commit_job(
            rem_maker, escena.appointment, step=paso, scheduled_for=AHORA - timedelta(minutes=1)
        )
    sender = FakeSender(W)
    configuracion = dispatch_settings(settings)

    await asyncio.gather(
        run_tick(rem_maker, {W: sender}, configuracion, now=lambda: AHORA),
        run_tick(rem_maker, {W: sender}, configuracion, now=lambda: AHORA),
    )
    await run_tick(rem_maker, {W: sender}, configuracion, now=lambda: AHORA)

    assert sorted(m.template_name for m in sender.sent) == [
        "recordatorio_24h_v1",
        "recordatorio_72h_v1",
        "turno_creado_v1",
    ]
    assert set(_estados(await read_jobs(rem_maker, escena.appointment.id)).values()) == {"sent"}


async def test_opt_out_a_mitad_de_la_secuencia_salta_lo_que_falta(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True)
    async with rem_maker() as session:
        turno = (
            await session.execute(
                select(Appointment).where(Appointment.id == escena.appointment.id)
            )
        ).scalar_one()
        await schedule_new(session, turno, now=AHORA)
        await session.commit()
    inicio = escena.appointment.starts_at
    reloj = MutableClock(current=inicio - timedelta(hours=72))
    sender = FakeSender(W)
    configuracion = dispatch_settings(settings)

    await run_tick(rem_maker, {W: sender}, configuracion, now=reloj)  # sale el alta y el de 72 h
    async with rem_maker() as session:
        paciente = await session.get(type(escena.patient), escena.patient.id)
        assert paciente is not None
        await ConsentService(session).record(
            paciente, W, ConsentStatus.OPT_OUT, ConsentSource.WHATSAPP_REPLY
        )
        await session.commit()
    reloj.current = inicio - timedelta(hours=24)
    await run_tick(rem_maker, {W: sender}, configuracion, now=reloj)
    reloj.current = inicio - timedelta(hours=3)
    await run_tick(rem_maker, {W: sender}, configuracion, now=reloj)

    assert _estados(await read_jobs(rem_maker, escena.appointment.id)) == {
        "created/whatsapp": "sent",
        "t_72h/whatsapp": "sent",
        "t_24h/whatsapp": "skipped",
        "t_3h/whatsapp": "skipped",
    }
    assert sorted(m.template_name for m in sender.sent) == [
        "recordatorio_72h_v1",
        "turno_creado_v1",
    ]
