"""Fixtures globales de tests (Postgres real; sin mocks de DB, regla dura 9)."""

import os
import uuid
from collections.abc import AsyncIterator, Iterator

import asyncpg
import pytest
from alembic import command
from app.core.database import async_database_url
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from tests.db_utils import alembic_config, run_admin

# La DB de tests es configurable: TEST_DATABASE_URL > DATABASE_URL (CI) > default local.
_DEFAULT_TEST_DB = "postgresql+asyncpg://turnos:ci-secret@localhost:5432/turnos_test"
os.environ["DATABASE_URL"] = (
    os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL") or _DEFAULT_TEST_DB
)
# Entorno mínimo para que Settings() falle-rápido pase en tests.
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "test-secret-no-produccion")


@pytest.fixture()
def anyio_backend() -> str:
    """Backend para tests async."""
    return "asyncio"


@pytest.fixture(scope="session")
def migrated_database() -> None:
    """Aplica `alembic upgrade head` sobre la DB de tests una vez por sesión."""
    command.upgrade(alembic_config(), "head")


@pytest.fixture()
async def db_session(migrated_database: None) -> AsyncIterator[AsyncSession]:
    """Sesión sobre Postgres real: transacción externa + savepoints, rollback al final."""
    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]), poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            outer = await connection.begin()
            session = AsyncSession(
                bind=connection,
                join_transaction_mode="create_savepoint",
                expire_on_commit=False,
            )
            try:
                yield session
            finally:
                await session.close()
                await outer.rollback()
    finally:
        await engine.dispose()


@pytest.fixture()
def temp_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """DB temporal vacía: apunta DATABASE_URL a ella y la dropea al terminar.

    Se salta con motivo explícito si el rol no tiene CREATEDB.
    """
    name = f"turnos_tmp_{uuid.uuid4().hex[:12]}"
    try:
        run_admin(f'CREATE DATABASE "{name}"')
    except (asyncpg.InsufficientPrivilegeError, OSError) as exc:
        pytest.skip(f"No se puede crear DB temporal (falta CREATEDB): {type(exc).__name__}")
    rendered = (
        make_url(os.environ["DATABASE_URL"])
        .set(database=name)
        .render_as_string(hide_password=False)
    )
    monkeypatch.setenv("DATABASE_URL", rendered)
    try:
        yield rendered
    finally:
        run_admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
