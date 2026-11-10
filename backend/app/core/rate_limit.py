"""Rate-limit de autenticación respaldado en Redis (ventana fija).

El reloj y el almacenamiento son compartidos entre procesos (`api` + `worker`),
a diferencia del middleware global en memoria de C-01. El contador se crea y se
le pone TTL en un único script Lua para no dejar claves sin expiración si el
proceso muere entre `INCR` y `EXPIRE`.

Formato de configuración: `"<intentos>/<segundos>s"` (p. ej. `"5/60s"`).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from redis.asyncio import Redis

_SPEC_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d+)s\s*$")


def parse_window_spec(spec: str) -> tuple[int, float]:
    """Parsea `"<limit>/<seconds>s"`; error con el nombre del formato si no cumple."""
    match = _SPEC_RE.match(spec)
    if not match:
        raise ValueError("formato esperado '<intentos>/<segundos>s'")
    limit = int(match.group(1))
    window_s = float(match.group(2))
    if limit < 1 or window_s <= 0:
        raise ValueError("el límite y la ventana deben ser positivos")
    return limit, window_s


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    """Resultado de consumir un cupo en la ventana fija."""

    allowed: bool
    retry_after: int


def login_pair_key(ip: str, email: str) -> str:
    """Clave del par IP+email: el email nunca aparece en claro (solo su huella)."""
    digest = hashlib.sha256(f"{ip}|{email.strip().lower()}".encode()).hexdigest()
    return f"rl:login:pair:{digest}"


def login_ip_key(ip: str) -> str:
    """Clave del tope agregado por IP (frena pulverización de emails)."""
    return f"rl:login:ip:{ip}"


def refresh_ip_key(ip: str) -> str:
    """Clave del cupo de refresh/logout por IP."""
    return f"rl:refresh:ip:{ip}"


def password_key(user_id: object) -> str:
    """Clave del cupo de cambio de contraseña por usuario."""
    return f"rl:pwd:{user_id}"


_HIT_LUA = """
local actual = redis.call('INCR', KEYS[1])
if actual == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {actual, ttl}
"""


async def hit(redis: Redis, key: str, limit: int, window_s: float) -> RateLimitResult:
    """Consume un intento y devuelve si sigue dentro del cupo y cuándo reintentar.

    Redis caído propaga la excepción: el llamador decide el 503 fail-closed
    (`auth_unavailable`); nunca se degrada a "permitir".
    """
    actual, ttl = await redis.eval(_HIT_LUA, 1, key, str(int(window_s)))  # type: ignore[misc]
    usado = int(actual)
    restante = int(ttl) if int(ttl) > 0 else int(window_s)
    return RateLimitResult(allowed=usado <= limit, retry_after=restante)


def booking_read_key(ip: str) -> str:
    """Clave del cupo de lecturas públicas (catálogo/disponibilidad) por IP (C-07)."""
    return f"rl:booking:read:ip:{ip}"


def booking_create_ip_key(ip: str) -> str:
    """Clave del cupo de reservas públicas por IP (C-07, RN-ON-03)."""
    return f"rl:booking:create:ip:{ip}"


def booking_create_slug_key(clinic_id: object) -> str:
    """Clave del cupo de reservas públicas por clínica: solo con slug resuelto (C-07)."""
    return f"rl:booking:create:slug:{clinic_id}"


def waitlist_join_ip_key(ip: str) -> str:
    """Cupo de anotaciones públicas en la lista de espera por IP (C-12, D7)."""
    return f"rl:waitlist:join:ip:{ip}"


def waitlist_join_slug_key(clinic_id: object) -> str:
    """Cupo de anotaciones públicas por clínica (C-12, D7)."""
    return f"rl:waitlist:join:slug:{clinic_id}"


def waitlist_offer_read_ip_key(ip: str) -> str:
    return f"rl:waitlist:offer:read:ip:{ip}"


def waitlist_offer_read_token_key(token_sha256: str) -> str:
    return f"rl:waitlist:offer:read:token:{token_sha256}"


def waitlist_offer_write_ip_key(ip: str) -> str:
    return f"rl:waitlist:offer:write:ip:{ip}"


def waitlist_offer_write_token_key(token_sha256: str) -> str:
    return f"rl:waitlist:offer:write:token:{token_sha256}"


def manage_read_ip_key(ip: str) -> str:
    """Clave del cupo de lecturas de gestión por IP (C-08, D10)."""
    return f"rl:manage:read:ip:{ip}"


def manage_read_token_key(token_sha256: str) -> str:
    """Clave del cupo de lecturas por token: el SHA-256, nunca el token (C-08, D10)."""
    return f"rl:manage:read:token:{token_sha256}"


def manage_write_ip_key(ip: str) -> str:
    """Clave del cupo de escrituras de gestión por IP (C-08, D10)."""
    return f"rl:manage:write:ip:{ip}"


def manage_write_token_key(token_sha256: str) -> str:
    """Clave del cupo de escrituras por token: el SHA-256, nunca el token (C-08, D10)."""
    return f"rl:manage:write:token:{token_sha256}"
