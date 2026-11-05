"""Runtime del worker: cron por minuto sobre ARQ y armado desde los settings (C-09, D12)."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest
from app.core.settings import Settings
from app.models import ReminderChannel, ReminderStatus
from app.worker import entrypoint
from app.worker.settings import build_worker_settings, on_shutdown, on_startup, reminder_tick
from arq.worker import create_worker
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.reminder_helpers import AHORA, commit_job, commit_scene, read_jobs

BASE = {
    "DATABASE_URL": "postgresql+asyncpg://turnos:clave@localhost:5432/turnos_test",
    "REDIS_URL": "redis://localhost:6379/0",
    "JWT_SECRET": "s" * 32,
}


def _settings(**cambios: object) -> Settings:
    return Settings.model_validate({**BASE, **cambios})


def test_el_worker_declara_un_cron_por_minuto_y_la_concurrencia_configurada() -> None:
    configuracion = build_worker_settings(_settings(REMINDER_WORKER_CONCURRENCY=4))

    [cron_job] = configuracion["cron_jobs"]
    assert cron_job.name == "cron:reminder_tick"
    assert cron_job.minute is None and cron_job.hour is None  # todos los minutos
    assert cron_job.second in (0, {0})
    assert cron_job.run_at_startup is True
    assert cron_job.unique is True
    assert configuracion["max_jobs"] == 4
    assert configuracion["on_startup"] is on_startup
    assert configuracion["on_shutdown"] is on_shutdown
    assert reminder_tick in configuracion["functions"]
    assert configuracion["redis_settings"].host == "localhost"
    assert configuracion["redis_settings"].database == 0


async def test_arq_acepta_la_configuracion_y_arma_el_worker() -> None:
    worker = create_worker(build_worker_settings(_settings()))

    assert [c.name for c in worker.cron_jobs] == ["cron:reminder_tick"]
    assert worker.max_jobs == 10


@pytest.mark.integration
async def test_on_startup_arma_engine_sender_y_reloj_segun_los_settings(
    reminders_db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REMINDER_WHATSAPP_PROVIDER", "fake")
    monkeypatch.setenv("REMINDER_EMAIL_PROVIDER", "disabled")
    ctx: dict[str, Any] = {}

    await on_startup(ctx)
    try:
        assert set(ctx["senders"]) == {ReminderChannel.WHATSAPP}
        assert ctx["settings"].REMINDER_WHATSAPP_PROVIDER == "fake"
        assert ctx["clock"]().tzinfo is not None
    finally:
        await on_shutdown(ctx)
    await on_shutdown(ctx)  # idempotente


@pytest.mark.integration
async def test_el_cron_corre_un_tick_que_envia_lo_vencido(
    reminders_db_url: str,
    rem_maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REMINDER_WHATSAPP_PROVIDER", "fake")
    monkeypatch.setenv("MANAGE_LINK_SECRET", "firma-de-links-solo-para-tests-32-bytes-ok")
    escena = await commit_scene(rem_maker, opt_in=True)
    await commit_job(rem_maker, escena.appointment, scheduled_for=AHORA - timedelta(minutes=1))
    ctx: dict[str, Any] = {}
    await on_startup(ctx)
    ctx["clock"] = lambda: AHORA
    try:
        await reminder_tick(ctx)
    finally:
        await on_shutdown(ctx)

    [job] = (await read_jobs(rem_maker, escena.appointment.id)).values()
    assert job.status is ReminderStatus.SENT
    assert job.provider_message_id is not None


def test_el_entrypoint_falla_nombrando_las_variables_que_faltan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        asyncio.run(entrypoint.main())

    assert "REDIS_URL" in str(exc_info.value) and "DATABASE_URL" in str(exc_info.value)
