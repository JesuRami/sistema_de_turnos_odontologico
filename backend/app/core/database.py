"""Utilidades de conexión a Postgres (driver async asyncpg)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_ASYNC_PREFIX = "postgresql+asyncpg://"
_SYNC_PREFIXES = ("postgresql://", "postgres://")


def async_database_url(url: str) -> str:
    """Devuelve la URL con driver asyncpg; rechaza otros drivers sin exponer credenciales."""
    if url.startswith(_ASYNC_PREFIX):
        return url
    for prefix in _SYNC_PREFIXES:
        if url.startswith(prefix):
            return _ASYNC_PREFIX + url[len(prefix) :]
    raise ValueError("DATABASE_URL debe ser postgresql[+asyncpg]://")


def create_engine(database_url: str) -> AsyncEngine:
    """Engine async del proceso (`pool_pre_ping` evita conexiones muertas)."""
    return create_async_engine(async_database_url(database_url), pool_pre_ping=True)


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Fábrica de sesiones por request; sin expirar objetos tras el commit."""
    return async_sessionmaker(engine, expire_on_commit=False)
