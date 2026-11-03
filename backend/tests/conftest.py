"""Fixtures globales de tests (Postgres y Redis reales; sin mocks, regla dura 9).

Los tests que usan infraestructura declaran las fixtures `db_session`,
`temp_database`, `redis_client` o `app_client`. Si el servicio no está
disponible en la máquina local, se saltan con un motivo explícito; CI siempre
levanta PostgreSQL 15 y Redis 7, por lo que allí corren completos.
"""

import asyncio
import os
import socket
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import asyncpg
import httpx
import pytest
from alembic import command
from app.core.database import async_database_url
from app.core.deps import get_db
from app.core.redis import create_redis_client, get_redis
from app.core.settings import Settings
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from tests.db_utils import alembic_config, run_admin

# La DB de tests es configurable: TEST_DATABASE_URL > DATABASE_URL (CI) > default local.
_DEFAULT_TEST_DB = "postgresql+asyncpg://turnos:ci-secret@localhost:5432/turnos_test"
os.environ["DATABASE_URL"] = (
    os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL") or _DEFAULT_TEST_DB
)
# Entorno mínimo para que Settings() falle-rápido pase en tests.
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
# ≥32 bytes: el arranque rechaza secretos cortos desde C-03.
os.environ.setdefault("JWT_SECRET", "test-secret-no-produccion-32-bytes-minimo")


@dataclass
class MutableClock:
    """Reloj inyectable para emitir tokens vencidos sin `sleep`."""

    current: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __call__(self) -> datetime:
        return self.current

    def advance(self, **delta: float) -> datetime:
        self.current = self.current + timedelta(**delta)
        return self.current


def _tcp_available(url: str) -> bool:
    """True si el host:puerto de la URL acepta una conexión TCP rápida."""
    try:
        parsed = make_url(url)
    except Exception:
        return False
    host = parsed.host or "localhost"
    port = parsed.port or 5432
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _services() -> dict[str, bool]:
    return {
        "postgres": _tcp_available(os.environ["DATABASE_URL"]),
        "redis": _tcp_available(os.environ.get("REDIS_URL", "")),
    }


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Marca los tests de infraestructura y los salta si el servicio no está local."""
    _ = config
    disponibles = _services()
    db_reason = (
        "PostgreSQL no disponible en "
        f"{os.environ['DATABASE_URL']} (levantar compose o correr en CI)"
    )
    redis_reason = (
        "Redis no disponible en "
        f"{os.environ.get('REDIS_URL', '')} (levantar compose o correr en CI)"
    )
    for item in items:
        fixtures = set(getattr(item, "fixturenames", ()))
        necesita_db = bool(fixtures & {"db_session", "temp_database", "committed_engine"})
        necesita_redis = "redis_client" in fixtures
        es_integracion = item.get_closest_marker("integration") is not None
        if es_integracion:
            item.add_marker(pytest.mark.integration)
        if necesita_db or necesita_redis:
            item.add_marker(pytest.mark.integration)
        if (necesita_db and not disponibles["postgres"]) or (
            necesita_redis and not disponibles["redis"]
        ):
            razones = []
            if necesita_db and not disponibles["postgres"]:
                razones.append(db_reason)
            if necesita_redis and not disponibles["redis"]:
                razones.append(redis_reason)
            item.add_marker(pytest.mark.skip(reason="; ".join(razones)))


@pytest.fixture()
def anyio_backend() -> str:
    """Backend para tests async."""
    return "asyncio"


@pytest.fixture()
def settings() -> Settings:
    """Settings de test (ENV=dev, secretos de prueba ≥32 bytes)."""
    return Settings()  # type: ignore[call-arg]


@pytest.fixture()
def clock() -> MutableClock:
    """Reloj mutable para tests de expiración."""
    return MutableClock()


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
async def redis_client(settings: Settings) -> AsyncIterator[Redis]:
    """Cliente Redis real en la base lógica de auth; FLUSHDB por test."""
    client = create_redis_client(settings)
    try:
        await client.ping()
    except Exception:
        await client.aclose()
        pytest.skip(
            f"Redis no disponible en {settings.REDIS_URL} " "(levantar compose o correr en CI)"
        )
    await client.flushdb()
    try:
        yield client
    finally:
        await client.flushdb()
        await client.aclose()


@pytest.fixture()
def app_instance(settings: Settings, db_session: AsyncSession, redis_client: Redis) -> FastAPI:
    """App de test con `get_db`/`get_redis` apuntando a los fixtures reales."""
    from app.main import create_app  # import diferido: Settings requiere el env de arriba

    app = create_app(settings)

    async def _override_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    async def _override_redis() -> Redis:
        return redis_client

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_redis] = _override_redis
    app.state.sessionmaker = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    return app


@pytest.fixture()
def client_factory(app_instance: FastAPI) -> Callable[..., httpx.AsyncClient]:
    """Fábrica de clientes httpx con cookie jar y IP de origen configurable."""

    def _make(ip: str = "127.0.0.1") -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app_instance, client=(ip, 12345)),
            base_url="http://test",
            timeout=15.0,
        )

    return _make


@pytest.fixture()
async def app_client(
    client_factory: Callable[..., httpx.AsyncClient],
) -> AsyncIterator[httpx.AsyncClient]:
    """Cliente HTTP de la app real (cookie jar persistente entre requests)."""
    client = client_factory()
    try:
        yield client
    finally:
        await client.aclose()


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


@pytest.fixture()
async def committed_engine(temp_database: str) -> AsyncIterator[AsyncEngine]:
    """Engine sobre una DB temporal migrada donde los commits son reales (carreras, atomicidad).

    Cada test recibe su propia DB y se dropea al final: nada queda en la DB compartida.
    """
    # Alembic corre su propio `asyncio.run`: fuera del loop del test.
    await asyncio.to_thread(command.upgrade, alembic_config(), "head")
    engine = create_async_engine(async_database_url(temp_database), poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


# Lunes 2030-01-07 08:00 en Buenos Aires (11:00 UTC): antes de abrir la agenda del día.
AGENDA_NOW = datetime(2030, 1, 7, 11, 0, tzinfo=UTC)


@pytest.fixture()
def agenda_clock(app_instance: FastAPI) -> MutableClock:
    """Reloj fijo inyectado en la app (`get_now`) para los tests de turnos (C-05)."""
    from app.common.clock import get_now

    reloj = MutableClock(current=AGENDA_NOW)
    app_instance.dependency_overrides[get_now] = lambda: reloj.current
    return reloj
