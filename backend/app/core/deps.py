"""Dependencias FastAPI compartidas: sesión de DB y principal autenticado (C-03)."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import Depends, Request
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.exceptions import DomainError
from app.common.principal import Principal
from app.core.jwt import TokenError, decode_access_token
from app.core.logs import clinic_id_var
from app.core.redis import get_redis
from app.core.settings import Settings, get_settings
from app.models import User
from app.modules.auth.sessions import session_alive


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """Sesión async por request; el engine/`sessionmaker` viven en el `lifespan`."""
    maker = cast(async_sessionmaker[AsyncSession], request.app.state.sessionmaker)
    async with maker() as session:
        yield session


# C-14 (D6): un JWT HS256 de este sistema mide ~400 bytes; el tope corta basura antes de
# decodificar y el charset/estructura descartan lo que no puede ser un JWS compacto.
_MAX_TOKEN_CHARS = 4096
_JWT_SHAPE = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
CHALLENGE = {"WWW-Authenticate": "Bearer"}


def unauthorized(code: str) -> DomainError:
    """`401` con el desafío `WWW-Authenticate: Bearer` (RFC 6750)."""
    return DomainError(401, code, headers=dict(CHALLENGE))


def _bearer_token(request: Request) -> str:
    """Extrae el token de `Authorization: Bearer`; sin credencial es `401` (nunca 403)."""
    header = request.headers.get("Authorization", "")
    scheme, _, value = header.partition(" ")
    token = value.strip()
    if scheme.lower() != "bearer" or not token:
        raise unauthorized("token_invalid")
    if len(token) > _MAX_TOKEN_CHARS or not _JWT_SHAPE.match(token):
        raise unauthorized("token_invalid")
    return token


async def get_current_principal(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Principal:
    """Valida el access y reconstruye el principal desde la fila de `user`.

    Orden: firma/claims → sesión viva en Redis → usuario activo por
    `(id, clinic_id)`. Redis caído es `503 auth_unavailable` (fail-closed),
    nunca `401` ni "sin sesión". Cualquier inconsistencia del token o de la
    sesión es `401` con código corto, sin detalle de la causa.
    """
    token = _bearer_token(request)
    try:
        claims = decode_access_token(token, settings)
    except TokenError as exc:
        raise unauthorized(exc.code) from None

    try:
        alive = await session_alive(redis, claims.sid)
    except RedisError:
        raise DomainError(503, "auth_unavailable") from None
    if not alive:
        raise unauthorized("invalid_session")

    clinic_id_var.set(str(claims.clinic_id))
    # Columnas explícitas (regla 8): el principal jamás arrastra el hash.
    stmt = select(
        User.id,
        User.clinic_id,
        User.email,
        User.role,
        User.professional_id,
        User.active,
        User.must_change_password,
    ).where(User.id == claims.user_id, User.clinic_id == claims.clinic_id)
    row = (await session.execute(stmt)).one_or_none()
    if row is None or not bool(row.active):
        raise unauthorized("invalid_session")

    return Principal(
        user_id=row.id,
        clinic_id=row.clinic_id,
        email=str(row.email),
        roles=frozenset({row.role}),
        professional_id=row.professional_id,
        sid=claims.sid,
        must_change_password=bool(row.must_change_password),
    )
