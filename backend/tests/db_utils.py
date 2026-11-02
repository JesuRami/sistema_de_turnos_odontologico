"""Utilidades de tests contra Postgres real (sin mocks de DB, regla dura 9)."""

import asyncio
import os
from pathlib import Path

import asyncpg
from alembic.config import Config
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]


def alembic_config() -> Config:
    """Config de Alembic anclada a la raíz del repo y sin tocar el logging de pytest."""
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    cfg.attributes["configure_logger"] = False
    return cfg


async def admin_execute(sql: str) -> None:
    """Ejecuta una sentencia (p. ej. CREATE DATABASE) en la DB `postgres` del servidor."""
    url = make_url(os.environ["DATABASE_URL"])
    conn = await asyncpg.connect(
        user=url.username,
        password=url.password,
        host=url.host,
        port=url.port,
        database="postgres",
    )
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


def run_admin(sql: str) -> None:
    """Versión síncrona de `admin_execute` para fixtures síncronas."""
    asyncio.run(admin_execute(sql))


async def _fetch(sql: str, database_url: str) -> list[tuple[object, ...]]:
    url = make_url(database_url)
    conn = await asyncpg.connect(
        user=url.username,
        password=url.password,
        host=url.host,
        port=url.port,
        database=url.database,
    )
    try:
        return [tuple(row) for row in await conn.fetch(sql)]
    finally:
        await conn.close()


def fetch_rows(sql: str, database_url: str) -> list[tuple[object, ...]]:
    """Consulta de solo lectura (síncrona) contra la DB indicada."""
    return asyncio.run(_fetch(sql, database_url))
