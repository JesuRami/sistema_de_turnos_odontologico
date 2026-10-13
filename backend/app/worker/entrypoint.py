"""Entrypoint del worker async (C-01: ocioso sano; scheduler real en C-09).

Decisión aprobada: ARQ (async nativo, liviano). Misma imagen que `api`,
comando distinto (un proceso por contenedor — regla dura 12). Swappable a
Celery/Dramatiq tocando solo dependencia + este módulo.

C-01: conecta Redis + Postgres, logea y queda idle (sin jobs).
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

    conn = await asyncpg.connect(database_url, timeout=5)
    try:
        return True
    finally:
        await conn.close()


async def idle_forever() -> None:
    """Loop ocioso sano (el scheduler de reminders llega en C-09)."""
    while True:
        logger.info("worker idle (scheduler llega en C-09)")
        await asyncio.sleep(60)


async def main() -> None:
    """Arranca el worker: verifica dependencias y queda idle."""
    logging.basicConfig(level=logging.INFO)
    redis_url = os.environ.get("REDIS_URL", "")
    database_url = os.environ.get("DATABASE_URL", "")
    if not redis_url or not database_url:
        raise SystemExit("REDIS_URL y DATABASE_URL son requeridas por el worker")
    redis_ok = await check_redis(redis_url)
    pg_ok = await check_postgres(database_url)
    logger.info("worker conectado: redis=%s postgres=%s", redis_ok, pg_ok)

    # Hook ARQ (se materializa con funciones en C-09; hoy solo valida la lib).
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(RedisSettings.from_dsn(redis_url))
        await pool.close()
        logger.info("arq pool ok (sin funciones hasta C-09)")
    except Exception as exc:  # noqa: BLE001 — scaffolding: solo log
        logger.warning("arq no disponible aún: %s", exc)

    await idle_forever()


if __name__ == "__main__":
    asyncio.run(main())
