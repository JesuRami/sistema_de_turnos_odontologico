"""Utilidades de conexión a Postgres (driver async asyncpg)."""

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
