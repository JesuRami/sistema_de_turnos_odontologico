"""Helpers de autenticación para tests (datos sintéticos, sesión real en Redis)."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.jwt import encode_access_token
from app.core.settings import Settings
from app.models import User, UserRole
from app.modules.auth.sessions import create_session
from redis.asyncio import Redis


@dataclass(frozen=True, slots=True)
class AuthSession:
    """Sesión emitida para un usuario de test."""

    sid: str
    refresh_token: str
    access_token: str
    headers: dict[str, str]


async def issue_session(
    redis: Redis,
    settings: Settings,
    user: User,
    *,
    ttl_s: int | None = None,
    roles: list[UserRole] | None = None,
) -> AuthSession:
    """Crea una familia de refresh y un access válido para `user`."""
    tokens = await create_session(
        redis,
        user_id=user.id,
        clinic_id=user.clinic_id,
        ttl_s=ttl_s or settings.JWT_REFRESH_DAYS * 86400,
    )
    access, _ = encode_access_token(
        user_id=user.id,
        clinic_id=user.clinic_id,
        roles=roles if roles is not None else [user.role],
        email=user.email,
        sid=tokens.sid,
        settings=settings,
    )
    return AuthSession(
        sid=tokens.sid,
        refresh_token=tokens.refresh_token,
        access_token=access,
        headers={"Authorization": f"Bearer {access}"},
    )


def bearer(token: str) -> dict[str, str]:
    """Encabezado Authorization para un token dado."""
    return {"Authorization": f"Bearer {token}"}


def sid_of(refresh_token: str) -> str:
    """`sid` de un refresh `<sid>.<secreto>` (no secreto)."""
    return refresh_token.split(".", 1)[0]
