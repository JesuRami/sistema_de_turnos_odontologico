"""Sesiones del personal en Redis: familia de refresh, rotación CAS y revocación.

Esquema (design §4):

- `auth:sess:{sid}` Hash `uid/cid/created_at/gen`, TTL absoluto `JWT_REFRESH_DAYS`.
- `auth:rt:{sid}` Hash `cur_hash/prev_hash/gen/uid/cid/exp`, mismo TTL.
- `auth:user:{uid}` Set de `sid` para revocar todas las sesiones sin `SCAN`.

El refresh es opaco (`<sid>.<secreto>`) y en Redis solo se guarda
`sha256(secreto)`. La rotación y la detección de reuso ocurren en un único
script Lua (compare-and-swap serializado por Redis): dos rotaciones simultáneas
no pueden emitir dos refresh válidos. Sin ventana de gracia (decisión 2): el
perdedor se trata como reuso y revoca la familia, por eso la SPA de C-06 debe
hacer refresh single-flight.
"""

from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, cast

from redis.asyncio import Redis
from redis.exceptions import NoScriptError

_GENESIS = ""
_ROTATE_LUA = """
if redis.call('EXISTS', KEYS[2]) == 0 then
  return {'missing'}
end
local cur = redis.call('HGET', KEYS[1], 'cur_hash')
if not cur then
  return {'missing'}
end
local prev = redis.call('HGET', KEYS[1], 'prev_hash')
local gen = tonumber(redis.call('HGET', KEYS[1], 'gen')) or 0
local uid = redis.call('HGET', KEYS[1], 'uid')
local cid = redis.call('HGET', KEYS[1], 'cid')
if ARGV[1] == cur then
  redis.call('HSET', KEYS[1], 'prev_hash', cur, 'cur_hash', ARGV[2], 'gen', gen + 1)
  redis.call('HSET', KEYS[2], 'gen', gen + 1)
  return {'rotated', tostring(gen + 1), uid or '', cid or ''}
elseif prev and prev ~= '' and ARGV[1] == prev then
  redis.call('DEL', KEYS[1], KEYS[2])
  -- Clave dinámica: Redis de una instancia (v1); con Cluster habría que usar hash tags.
  if uid and uid ~= '' then
    redis.call('SREM', 'auth:user:' .. uid, ARGV[3])
  end
  return {'reuse', tostring(gen), uid or '', cid or ''}
else
  return {'invalid'}
end
"""
# Identificador del script para EVALSHA (no es un secreto).
_SHA = hashlib.sha1(_ROTATE_LUA.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class SessionTokens:
    """Sesión recién creada (el refresh en claro solo existe en memoria del cliente)."""

    sid: str
    refresh_token: str
    ttl_s: int


@dataclass(frozen=True, slots=True)
class RotationResult:
    """Resultado de rotar un refresh: `rotated | reuse | invalid | missing`."""

    status: str
    user_id: uuid.UUID | None = None
    clinic_id: uuid.UUID | None = None
    generation: int | None = None
    refresh_token: str | None = None


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def refresh_secret(refresh_token: str) -> str:
    """Parte secreta de `<sid>.<secreto>` (vacía si el formato es inválido)."""
    _sid, _, secreto = refresh_token.partition(".")
    return secreto


def _parse_refresh(refresh_token: str) -> tuple[str, str] | None:
    sid, separador, secreto = refresh_token.partition(".")
    if not separador or not sid or not secreto:
        return None
    try:
        uuid.UUID(sid)
    except ValueError:
        return None
    return sid, secreto


async def _eval_cas(redis: Redis, keys: list[str], args: list[str]) -> list[Any]:
    """Ejecuta el CAS con EVALSHA y cae a EVAL si el script no está cacheado."""
    try:
        resultado = await cast(Awaitable[Any], redis.evalsha(_SHA, len(keys), *keys, *args))
    except NoScriptError:
        resultado = await cast(Awaitable[Any], redis.eval(_ROTATE_LUA, len(keys), *keys, *args))
    return list(resultado)


async def create_session(
    redis: Redis, *, user_id: uuid.UUID, clinic_id: uuid.UUID, ttl_s: int
) -> SessionTokens:
    """Crea la familia de refresh y registra el `sid` en el set del usuario."""
    sid = str(uuid.uuid4())
    secreto = secrets.token_urlsafe(32)
    ahora = int(time.time())
    sess_key = f"auth:sess:{sid}"
    rt_key = f"auth:rt:{sid}"
    user_key = f"auth:user:{user_id}"

    pipe = redis.pipeline(transaction=True)
    pipe.hset(
        sess_key,
        mapping={
            "uid": str(user_id),
            "cid": str(clinic_id),
            "created_at": str(ahora),
            "gen": "0",
        },
    )
    pipe.expire(sess_key, ttl_s)
    pipe.hset(
        rt_key,
        mapping={
            "cur_hash": _digest(secreto),
            "prev_hash": _GENESIS,
            "gen": "0",
            "uid": str(user_id),
            "cid": str(clinic_id),
            # Vigencia absoluta: no se mueve en las rotaciones.
            "exp": str(ahora + ttl_s),
        },
    )
    pipe.expire(rt_key, ttl_s)
    pipe.sadd(user_key, sid)
    pipe.expire(user_key, ttl_s)
    await pipe.execute()

    return SessionTokens(sid=sid, refresh_token=f"{sid}.{secreto}", ttl_s=ttl_s)


async def rotate(redis: Redis, refresh_token: str) -> RotationResult:
    """Rota el refresh de forma atómica; el anterior pasa a ser señal de reuso."""
    parseado = _parse_refresh(refresh_token)
    if parseado is None:
        return RotationResult(status="invalid")
    sid, secreto = parseado
    nuevo_secreto = secrets.token_urlsafe(32)

    crudo = await _eval_cas(
        redis,
        [f"auth:rt:{sid}", f"auth:sess:{sid}"],
        [_digest(secreto), _digest(nuevo_secreto), sid],
    )
    estado = str(crudo[0]) if crudo else "invalid"

    if estado == "rotated":
        return RotationResult(
            status="rotated",
            user_id=uuid.UUID(str(crudo[2])),
            clinic_id=uuid.UUID(str(crudo[3])),
            generation=int(crudo[1]),
            refresh_token=f"{sid}.{nuevo_secreto}",
        )
    if estado == "reuse":
        return RotationResult(
            status="reuse",
            user_id=uuid.UUID(str(crudo[2])) if len(crudo) > 2 and crudo[2] else None,
            clinic_id=uuid.UUID(str(crudo[3])) if len(crudo) > 3 and crudo[3] else None,
            generation=int(crudo[1]) if len(crudo) > 1 else None,
        )
    if estado == "missing":
        return RotationResult(status="missing")
    return RotationResult(status="invalid")


async def revoke(redis: Redis, sid: str, user_id: uuid.UUID) -> None:
    """Revoca una sesión; idempotente (segunda llamada no falla)."""
    pipe = redis.pipeline(transaction=True)
    pipe.delete(f"auth:rt:{sid}", f"auth:sess:{sid}")
    pipe.srem(f"auth:user:{user_id}", sid)
    await pipe.execute()


async def revoke_by_sid(redis: Redis, sid: str) -> None:
    """Revoca sin conocer el usuario (logout solo con cookie): lee `uid` del hash."""
    uid = await cast(Awaitable[Any], redis.hget(f"auth:rt:{sid}", "uid"))
    if uid:
        await revoke(redis, sid, uuid.UUID(str(uid)))
        return
    await redis.delete(f"auth:rt:{sid}", f"auth:sess:{sid}")


async def revoke_all(redis: Redis, user_id: uuid.UUID) -> int:
    """Revoca todas las sesiones del usuario y devuelve cuántas familias eliminó."""
    user_key = f"auth:user:{user_id}"
    sids = [str(sid) for sid in await cast(Awaitable[Any], redis.smembers(user_key))]
    pipe = redis.pipeline(transaction=True)
    for sid in sids:
        pipe.delete(f"auth:rt:{sid}", f"auth:sess:{sid}")
    pipe.delete(user_key)
    await pipe.execute()
    return len(sids)


async def session_alive(redis: Redis, sid: str) -> bool:
    """True si la familia de sesión sigue registrada (access vigente)."""
    return bool(await redis.exists(f"auth:sess:{sid}"))
