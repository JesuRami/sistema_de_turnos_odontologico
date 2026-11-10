"""Configuración del worker ARQ del motor de recordatorios (C-09, D12).

Un cron por minuto (`reminder_tick`) corre `run_tick`. ARQ deduplica el cron entre réplicas por id
de job, pero la garantía real contra el doble envío es `FOR UPDATE SKIP LOCKED` + la clave única
`(appointment_id, step, channel)` en Postgres: Redis solo evita ticks redundantes. La cola vive en
la base lógica de la `REDIS_URL` (0), separada de las sesiones de auth (`REDIS_AUTH_DB`).

La configuración se arma desde `Settings` (`build_worker_settings`) en vez de una clase de módulo,
así los tests la construyen sin tocar el entorno y los valores se leen una sola vez al arrancar.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from app.core.database import create_engine, create_sessionmaker
from app.core.settings import Settings, get_settings
from app.modules.reminders.dispatch import run_tick
from app.modules.reminders.senders import build_senders, close_senders
from app.modules.waiting_list.engine import run_waitlist_tick

logger = logging.getLogger("worker")

# Margen sobre el presupuesto del tick: un lote en vuelo puede terminar después de agotarlo.
_TICK_TIMEOUT_MARGIN_S = 60


async def on_startup(ctx: dict[str, Any]) -> None:
    """Arma engine, sessionmaker, senders y reloj del proceso."""
    settings = get_settings()
    engine = create_engine(settings.DATABASE_URL, settings, application_name="turnos-worker")
    senders = build_senders(settings)
    ctx.update(
        settings=settings,
        engine=engine,
        session_factory=create_sessionmaker(engine),
        senders=senders,
        clock=lambda: datetime.now(UTC),
    )
    logger.info(
        "worker de recordatorios listo: canales habilitados=%s",
        sorted(canal.value for canal in senders) or "ninguno",
    )


async def on_shutdown(ctx: dict[str, Any]) -> None:
    senders = ctx.pop("senders", None)
    if senders:
        await close_senders(senders)
    engine = ctx.pop("engine", None)
    if engine is not None:
        await engine.dispose()


async def reminder_tick(ctx: dict[str, Any]) -> None:
    """Un tick del motor: recupera leases, reclama lo vencido y lo envía."""
    await run_tick(ctx["session_factory"], ctx["senders"], ctx["settings"], now=ctx["clock"])


async def waitlist_tick(ctx: dict[str, Any]) -> None:
    """Un tick de la lista de espera (C-12, D4): vence ofertas, rota el hueco, vence entradas."""
    await run_waitlist_tick(ctx["session_factory"], ctx["settings"], now=ctx["clock"])


def build_worker_settings(settings: Settings) -> dict[str, Any]:
    """Diccionario que `arq.worker.create_worker` acepta como configuración."""
    return {
        "functions": [reminder_tick, waitlist_tick],
        "cron_jobs": [
            cron(
                reminder_tick,
                second=0,
                run_at_startup=True,
                unique=True,
                timeout=settings.REMINDER_TICK_BUDGET_S + _TICK_TIMEOUT_MARGIN_S,
                max_tries=1,
            ),
            # C-12 (D4): a mitad de minuto, para no competir con el tick de recordatorios.
            cron(
                waitlist_tick,
                second=30,
                run_at_startup=True,
                unique=True,
                timeout=settings.REMINDER_TICK_BUDGET_S + _TICK_TIMEOUT_MARGIN_S,
                max_tries=1,
            ),
        ],
        "on_startup": on_startup,
        "on_shutdown": on_shutdown,
        "redis_settings": RedisSettings.from_dsn(settings.REDIS_URL),
        "max_jobs": settings.REMINDER_WORKER_CONCURRENCY,
        "keep_result": 0,
    }
