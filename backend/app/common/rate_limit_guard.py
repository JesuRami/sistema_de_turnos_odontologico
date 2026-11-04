"""Consumo de cupos de rate-limit con 429/503 de dominio (compartido por auth y reserva pública).

Redis caído es falla cerrada: el código de `503` lo elige el llamador (`auth_unavailable`,
`booking_unavailable`); nunca se degrada a "permitir".
"""

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.common.exceptions import DomainError
from app.core.rate_limit import hit, parse_window_spec


async def consume(redis: Redis, key: str, spec: str, *, unavailable_code: str) -> None:
    """Consume un cupo de la ventana fija; `429 rate_limited` con `Retry-After` si se excede."""
    limit, window_s = parse_window_spec(spec)
    try:
        resultado = await hit(redis, key, limit, window_s)
    except RedisError:
        raise DomainError(503, unavailable_code) from None
    if not resultado.allowed:
        raise DomainError(429, "rate_limited", headers={"Retry-After": str(resultado.retry_after)})
