"""Utilidades de conexión a Postgres (driver async asyncpg).

C-14 (D4): cada conexión de la app y del worker lleva `statement_timeout`, `lock_timeout` e
`idle_in_transaction_session_timeout`. Una carrera sobre el mismo turno u oferta (locks
`FOR UPDATE` de C-05/C-12) espera como mucho `DB_LOCK_TIMEOUT_MS` y responde `409
concurrent_update` (ver `app.common.exceptions`) en vez de colgar al worker de uvicorn.
Las migraciones no pasan por acá: `alembic/env.py` crea su propio engine sin topes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    from app.core.settings import Settings

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


def server_settings(settings: Settings | None, application_name: str) -> dict[str, str]:
    """Parámetros de sesión de Postgres para cada conexión del pool (D4)."""
    valores = {"application_name": application_name}
    if settings is None:
        return valores
    topes = {
        "statement_timeout": settings.DB_STATEMENT_TIMEOUT_MS,
        "lock_timeout": settings.DB_LOCK_TIMEOUT_MS,
        "idle_in_transaction_session_timeout": settings.DB_IDLE_TX_TIMEOUT_MS,
    }
    for nombre, ms in topes.items():
        if ms > 0:
            valores[nombre] = str(ms)
    return valores


def create_engine(
    database_url: str,
    settings: Settings | None = None,
    *,
    application_name: str = "turnos-api",
) -> AsyncEngine:
    """Engine async del proceso (`pool_pre_ping` evita conexiones muertas)."""
    connect_args: dict[str, Any] = {"server_settings": server_settings(settings, application_name)}
    return create_async_engine(
        async_database_url(database_url), pool_pre_ping=True, connect_args=connect_args
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Fábrica de sesiones por request; sin expirar objetos tras el commit."""
    return async_sessionmaker(engine, expire_on_commit=False)
