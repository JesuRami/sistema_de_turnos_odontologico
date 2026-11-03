"""Cliente Redis compartido por proceso para sesiones y rate-limit de auth.

Una única conexión pool por app (creada en `create_app`, cerrada en el
`lifespan`), en lugar de `from_url` por request como en C-01. Las sesiones de
autenticación viven en una base lógica separada (`REDIS_AUTH_DB`) de la cola
del worker.

Falla de Redis = falla del camino autenticado: los consumidores responden `503`
fail-closed (`auth_unavailable`), nunca degradan a "sin sesión" ni "permitir".
"""

from __future__ import annotations

from typing import cast
from urllib.parse import urlsplit, urlunsplit

from fastapi import Request
from redis.asyncio import Redis

from app.core.settings import Settings


def auth_redis_url(settings: Settings) -> str:
    """URL de Redis para auth, apuntando a `REDIS_AUTH_DB`."""
    partes = urlsplit(settings.REDIS_URL)
    return urlunsplit(
        (partes.scheme, partes.netloc, f"/{settings.REDIS_AUTH_DB}", partes.query, partes.fragment)
    )


def create_redis_client(settings: Settings) -> Redis:
    """Crea el cliente compartido (lazy: no conecta hasta el primer comando)."""
    return cast(Redis, Redis.from_url(auth_redis_url(settings), decode_responses=True))


async def get_redis(request: Request) -> Redis:
    """Dependency: cliente compartido de la app (inyectable/override en tests)."""
    return cast(Redis, request.app.state.redis)
