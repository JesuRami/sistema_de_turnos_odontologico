"""Access tokens JWT del personal (C-03).

- HS256 pineado en servidor; `iss`/`aud`/`exp`/`iat` obligatorios y `leeway`
  acotado (regla dura 10).
- El token lleva `sid` (familia de sesión); la validez real la decide el
  registro de sesión en Redis (`get_current_principal`).
- `sub` es el UUID estable del usuario, nunca el email.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import ExpiredSignatureError, JWTError, jwt

from app.core.security import ALGORITHM_PIN
from app.core.settings import Settings
from app.models import UserRole

Clock = Callable[[], datetime]
_TOKEN_LEEWAY_S = 30
_REQUIRED_CLAIMS = (
    "exp",
    "iat",
    "iss",
    "aud",
    "sub",
    "type",
    "sid",
    "jti",
    "clinic_id",
    "roles",
    "email",
)


def utcnow() -> datetime:
    """Reloj por defecto; inyectable en tests para emitir tokens vencidos."""
    return datetime.now(UTC)


class TokenError(Exception):
    """Error de token con código público corto (sin detalle de la causa)."""

    code = "token_invalid"


class TokenExpiredError(TokenError):
    """El `exp` del token ya pasó."""

    code = "token_expired"


class TokenInvalidError(TokenError):
    """Firma, algoritmo o claims no aceptados."""

    code = "token_invalid"


@dataclass(frozen=True, slots=True)
class AccessClaims:
    """Claims ya validados de un access token."""

    user_id: uuid.UUID
    clinic_id: uuid.UUID
    roles: tuple[UserRole, ...]
    email: str
    jti: str
    sid: str
    issued_at: datetime
    expires_at: datetime


def encode_access_token(
    *,
    user_id: uuid.UUID,
    clinic_id: uuid.UUID,
    roles: Sequence[UserRole],
    email: str,
    sid: str,
    settings: Settings,
    clock: Clock = utcnow,
    jti: str | None = None,
) -> tuple[str, int]:
    """Emite un access token y devuelve `(token, expires_in_segundos)`."""
    emitido = clock()
    expira = emitido + timedelta(minutes=settings.JWT_ACCESS_MINUTES)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "clinic_id": str(clinic_id),
        "roles": [rol.value for rol in roles],
        "email": email,
        "jti": jti or str(uuid.uuid4()),
        "sid": sid,
        "type": "access",
        "iat": emitido,
        "exp": expira,
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
    }
    token = jwt.encode(payload, settings.JWT_SECRET.get_secret_value(), algorithm=ALGORITHM_PIN)
    return str(token), int((expira - emitido).total_seconds())


def _uuid_claim(value: object) -> uuid.UUID:
    if not isinstance(value, str):
        raise TokenInvalidError("token_invalid")
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise TokenInvalidError("token_invalid") from exc


def _epoch_claim(value: object) -> datetime:
    if not isinstance(value, int | float):
        raise TokenInvalidError("token_invalid")
    return datetime.fromtimestamp(value, tz=UTC)


def decode_access_token(token: str, settings: Settings) -> AccessClaims:
    """Valida firma, algoritmo, emisor, audiencia, exp y contrato de claims."""
    try:
        raw: dict[str, Any] = jwt.decode(
            token,
            settings.JWT_SECRET.get_secret_value(),
            algorithms=[ALGORITHM_PIN],
            audience=settings.JWT_AUDIENCE,
            issuer=settings.JWT_ISSUER,
            # python-jose no recibe `leeway` como kwarg: va dentro de `options`.
            options={"require": list(_REQUIRED_CLAIMS), "leeway": _TOKEN_LEEWAY_S},
        )
    except ExpiredSignatureError as exc:
        raise TokenExpiredError("token_expired") from exc
    except JWTError as exc:
        raise TokenInvalidError("token_invalid") from exc

    if raw.get("type") != "access":
        raise TokenInvalidError("token_invalid")

    sid = raw.get("sid")
    jti = raw.get("jti")
    email = raw.get("email")
    roles_raw = raw.get("roles")
    if not isinstance(sid, str) or not sid:
        raise TokenInvalidError("token_invalid")
    if not isinstance(jti, str) or not jti:
        raise TokenInvalidError("token_invalid")
    if not isinstance(email, str) or not email:
        raise TokenInvalidError("token_invalid")
    if not isinstance(roles_raw, list) or not roles_raw:
        raise TokenInvalidError("token_invalid")
    try:
        roles = tuple(UserRole(rol) for rol in roles_raw if isinstance(rol, str))
    except ValueError as exc:
        raise TokenInvalidError("token_invalid") from exc
    if len(roles) != len(roles_raw):
        raise TokenInvalidError("token_invalid")

    return AccessClaims(
        user_id=_uuid_claim(raw.get("sub")),
        clinic_id=_uuid_claim(raw.get("clinic_id")),
        roles=roles,
        email=email,
        jti=jti,
        sid=sid,
        issued_at=_epoch_claim(raw.get("iat")),
        expires_at=_epoch_claim(raw.get("exp")),
    )
