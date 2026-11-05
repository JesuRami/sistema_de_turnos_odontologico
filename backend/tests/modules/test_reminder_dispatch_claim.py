"""Reclamo de jobs del tick: sin duplicados, por lotes, con lease (C-09, D4)."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from app.core.settings import Settings
from app.models import (
    DeliveryEventType,
    NotificationTemplate,
    ReminderChannel,
    ReminderStatus,
)
from app.modules.reminders.dispatch import TickStats, run_tick
from app.modules.reminders.senders.fake import FakeSender
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.reminder_helpers import (
    AHORA,
    commit_job,
    commit_scene,
    dispatch_settings,
    read_events,
    read_jobs,
)

pytestmark = pytest.mark.integration

VENCIDO = AHORA - timedelta(minutes=1)


def _senders() -> dict[ReminderChannel, FakeSender]:
    return {
        ReminderChannel.WHATSAPP: FakeSender(ReminderChannel.WHATSAPP),
        ReminderChannel.EMAIL: FakeSender(ReminderChannel.EMAIL),
    }


async def _tick(
    maker: async_sessionmaker[AsyncSession],
    senders: dict[ReminderChannel, FakeSender],
    settings: Settings,
    **cambios: object,
) -> TickStats:
    return await run_tick(maker, senders, dispatch_settings(settings, **cambios), now=lambda: AHORA)


async def test_dos_ticks_simultaneos_envian_cada_job_una_sola_vez(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escenas = [await commit_scene(rem_maker, opt_in=True) for _ in range(10)]
    for escena in escenas:
        await commit_job(rem_maker, escena.appointment, scheduled_for=VENCIDO)
    senders = _senders()

    await asyncio.gather(_tick(rem_maker, senders, settings), _tick(rem_maker, senders, settings))

    assert len(senders[ReminderChannel.WHATSAPP].sent) == 10
    for escena in escenas:
        [job] = (await read_jobs(rem_maker, escena.appointment.id)).values()
        assert job.status is ReminderStatus.SENT
        assert job.attempts == 1
        assert job.provider_message_id is not None and job.provider_message_id.startswith("fake-")
    destinos = [m.to for m in senders[ReminderChannel.WHATSAPP].sent]
    assert len(set(destinos)) == 10


async def test_un_lote_grande_se_drena_en_varios_lotes(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True, starts_in=timedelta(days=300))
    pasos = [f"t_{n}h" for n in range(1, 121)]
    async with rem_maker() as session:
        await session.execute(
            pg_insert(NotificationTemplate)
            .values(
                [
                    {
                        "clinic_id": escena.clinic.id,
                        "channel": ReminderChannel.WHATSAPP,
                        "step": paso,
                        "meta_template_name": f"recordatorio_{paso}_v1",
                        "body_preview": "Hola {{nombre}} {{link}}",
                    }
                    for paso in pasos
                ]
            )
            .on_conflict_do_nothing()
        )
        await session.commit()
    for paso in pasos:
        await commit_job(rem_maker, escena.appointment, step=paso, scheduled_for=VENCIDO)
    senders = _senders()

    stats = await _tick(rem_maker, senders, settings)

    assert len(senders[ReminderChannel.WHATSAPP].sent) == 120
    assert stats.sent == 120
    assert stats.batches == 2  # 100 + 20
    estados = {j.status for j in (await read_jobs(rem_maker, escena.appointment.id)).values()}
    assert estados == {ReminderStatus.SENT}


async def test_el_tamano_del_lote_es_configurable(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True)
    for paso in ("t_72h", "t_24h", "t_3h", "created"):
        await commit_job(rem_maker, escena.appointment, step=paso, scheduled_for=VENCIDO)
    senders = _senders()

    stats = await _tick(rem_maker, senders, settings, REMINDER_BATCH_SIZE=3)

    assert stats.sent == 4 and stats.batches == 2


async def test_un_job_futuro_no_se_reclama(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True)
    await commit_job(rem_maker, escena.appointment, scheduled_for=AHORA + timedelta(minutes=5))
    senders = _senders()

    stats = await _tick(rem_maker, senders, settings)

    [job] = (await read_jobs(rem_maker, escena.appointment.id)).values()
    assert job.status is ReminderStatus.SCHEDULED and job.attempts == 0
    assert senders[ReminderChannel.WHATSAPP].sent == []
    assert stats.claimed == 0 and stats.batches == 0


async def test_con_el_proveedor_deshabilitado_el_job_queda_scheduled_sin_eventos(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True)
    job = await commit_job(rem_maker, escena.appointment, scheduled_for=VENCIDO)

    stats = await run_tick(rem_maker, {}, dispatch_settings(settings), now=lambda: AHORA)

    [leido] = (await read_jobs(rem_maker, escena.appointment.id)).values()
    assert leido.status is ReminderStatus.SCHEDULED and leido.attempts == 0
    assert await read_events(rem_maker, job.id) == []
    assert stats.claimed == 0


async def test_solo_se_reclaman_los_canales_habilitados(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True, email="paciente.ficticio@example.com")
    await commit_job(rem_maker, escena.appointment, step="t_24h", scheduled_for=VENCIDO)
    await commit_job(
        rem_maker,
        escena.appointment,
        step="t_24h",
        channel=ReminderChannel.EMAIL,
        scheduled_for=VENCIDO,
    )
    solo_email = {ReminderChannel.EMAIL: FakeSender(ReminderChannel.EMAIL)}

    await run_tick(rem_maker, solo_email, dispatch_settings(settings), now=lambda: AHORA)

    jobs = await read_jobs(rem_maker, escena.appointment.id)
    assert jobs[("t_24h", "email")].status is ReminderStatus.SENT
    assert jobs[("t_24h", "whatsapp")].status is ReminderStatus.SCHEDULED


# --------------------------------------------------------------------------- lease


async def test_un_lease_vencido_vuelve_a_scheduled_con_su_evento(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True)
    caido = await commit_job(
        rem_maker,
        escena.appointment,
        step="t_24h",
        status=ReminderStatus.SENDING,
        claimed_at=AHORA - timedelta(minutes=10),
        attempts=1,
        scheduled_for=VENCIDO,
    )
    reciente = await commit_job(
        rem_maker,
        escena.appointment,
        step="t_3h",
        status=ReminderStatus.SENDING,
        claimed_at=AHORA - timedelta(minutes=1),
        attempts=1,
        scheduled_for=VENCIDO,
    )

    stats = await run_tick(rem_maker, {}, dispatch_settings(settings), now=lambda: AHORA)

    jobs = await read_jobs(rem_maker, escena.appointment.id)
    assert jobs[("t_24h", "whatsapp")].status is ReminderStatus.SCHEDULED
    assert jobs[("t_24h", "whatsapp")].reason == "lease_expired"
    assert jobs[("t_24h", "whatsapp")].claimed_at is None
    assert jobs[("t_3h", "whatsapp")].status is ReminderStatus.SENDING
    assert [e.event_type for e in await read_events(rem_maker, caido.id)] == [
        DeliveryEventType.LEASE_EXPIRED
    ]
    assert await read_events(rem_maker, reciente.id) == []
    assert stats.recovered == 1


async def test_un_lease_vencido_se_reclama_y_envia_en_el_mismo_tick(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True)
    await commit_job(
        rem_maker,
        escena.appointment,
        status=ReminderStatus.SENDING,
        claimed_at=AHORA - timedelta(minutes=10),
        attempts=1,
        scheduled_for=VENCIDO,
    )
    senders = _senders()

    await _tick(rem_maker, senders, settings)

    [job] = (await read_jobs(rem_maker, escena.appointment.id)).values()
    assert job.status is ReminderStatus.SENT and job.attempts == 2
    assert len(senders[ReminderChannel.WHATSAPP].sent) == 1


async def test_un_lease_vencido_que_agoto_los_intentos_queda_failed(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True)
    await commit_job(
        rem_maker,
        escena.appointment,
        status=ReminderStatus.SENDING,
        claimed_at=AHORA - timedelta(minutes=10),
        attempts=3,
        scheduled_for=VENCIDO,
    )
    senders = _senders()

    await _tick(rem_maker, senders, settings)

    [job] = (await read_jobs(rem_maker, escena.appointment.id)).values()
    assert job.status is ReminderStatus.FAILED and job.reason == "lease_expired"
    assert senders[ReminderChannel.WHATSAPP].sent == []
