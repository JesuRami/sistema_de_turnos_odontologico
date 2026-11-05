"""Fixtures del despacho de recordatorios (C-09): Postgres real con commits reales.

El worker abre varias sesiones a la vez (reclamo, envíos concurrentes, resultados), así que no
puede correr sobre la sesión única con savepoints de `db_session`. Se crea UNA base temporal
migrada por módulo de tests y se la vacía antes de cada test (`TRUNCATE … CASCADE`): es mucho más
barato que migrar una base por test.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Iterator

import asyncpg
import pytest
from alembic import command
from app.core.database import async_database_url
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from tests.db_utils import alembic_config, run_admin


@pytest.fixture(scope="module")
def reminders_db_url() -> Iterator[str]:
    """Base temporal migrada a `head`, compartida por los tests de un módulo."""
    nombre = f"turnos_rem_{uuid.uuid4().hex[:12]}"
    try:
        run_admin(f'CREATE DATABASE "{nombre}"')
    except (asyncpg.InsufficientPrivilegeError, OSError) as exc:
        pytest.skip(f"No se puede crear DB temporal (falta CREATEDB): {type(exc).__name__}")
    url = (
        make_url(os.environ["DATABASE_URL"])
        .set(database=nombre)
        .render_as_string(hide_password=False)
    )
    previo = os.environ["DATABASE_URL"]
    os.environ["DATABASE_URL"] = url
    try:
        command.upgrade(alembic_config(), "head")
        yield url
    finally:
        os.environ["DATABASE_URL"] = previo
        run_admin(f'DROP DATABASE IF EXISTS "{nombre}" WITH (FORCE)')


@pytest.fixture()
async def rem_engine(reminders_db_url: str) -> AsyncIterator[AsyncEngine]:
    """Engine sobre la base del módulo, vacía para cada test."""
    engine = create_async_engine(async_database_url(reminders_db_url), poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE clinic CASCADE"))
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture()
def rem_maker(rem_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(rem_engine, expire_on_commit=False)
