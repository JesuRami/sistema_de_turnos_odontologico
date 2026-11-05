"""Entrypoint del worker async (C-01 scaffolding; scheduler del motor de recordatorios en C-09).

Decisión aprobada: ARQ (async nativo, liviano). Misma imagen que `api`,
comando distinto (un proceso por contenedor — regla dura 12). Swappable a
Celery/Dramatiq tocando solo dependencia + este módulo.

C-09: verifica Redis + Postgres y corre el worker ARQ con el cron por minuto del motor de
recordatorios (`app.worker.settings`). Si falta una dependencia aborta nombrando la variable.
"""

import asyncio
import logging
import os

logger = logging.getLogger("worker")


async def check_redis(redis_url: str) -> bool:
    """Verifica conectividad Redis (ping)."""
    import redis.asyncio as aioredis

    client = aioredis.from_url(redis_url)  # type: ignore[no-untyped-call]
    try:
        await client.ping()
        return True
    finally:
        await client.aclose()


async def check_postgres(database_url: str) -> bool:
    """Verifica conectividad Postgres (connect + close)."""
    import asyncpg

    # asyncpg no entiende el sufijo de driver de SQLAlchemy (`postgresql+asyncpg://`).
    conn = await asyncpg.connect(database_url.replace("+asyncpg", "", 1), timeout=5)
    try:
        return True
    finally:
        await conn.close()


async def main() -> None:
    """Arranca el worker: verifica dependencias y corre el cron del motor de recordatorios."""
    logging.basicConfig(level=logging.INFO)
    redis_url = os.environ.get("REDIS_URL", "")
    database_url = os.environ.get("DATABASE_URL", "")
    if not redis_url or not database_url:
        raise SystemExit("REDIS_URL y DATABASE_URL son requeridas por el worker")
    redis_ok = await check_redis(redis_url)
    pg_ok = await check_postgres(database_url)
    logger.info("worker conectado: redis=%s postgres=%s", redis_ok, pg_ok)

    from arq.worker import create_worker

    from app.core.settings import get_settings
    from app.worker.settings import build_worker_settings

    worker = create_worker(build_worker_settings(get_settings()))
    try:
        await worker.async_run()
    except asyncio.CancelledError:
        # ARQ cancela su tarea principal ante SIGTERM/SIGINT: es un apagado ordenado, no un error.
        logger.info("worker detenido")


if __name__ == "__main__":
    asyncio.run(main())
