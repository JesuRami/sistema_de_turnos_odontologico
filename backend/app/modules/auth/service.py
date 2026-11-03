"""Servicio de autenticación del personal (C-03).

Concentra login, refresh rotativo, logout y cambio de contraseña. Los routers
solo traducen HTTP; las reglas (auditoría, revocación, rehash, política) viven
aquí. Redis caído se traduce a `503 auth_unavailable` (fail-closed).
"""

from __future__ import annotations

import logging
import secrets
import uuid
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import cast

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import DomainError
from app.common.principal import Principal
from app.core.jwt import (
    TokenError,
    decode_access_token,
    encode_access_token,
    utcnow,
)
from app.core.security import hash_password, needs_rehash, verify_password
from app.core.settings import Settings
from app.models import AuthEventType, Clinic, User
from app.modules.auth.audit import record_best_effort, record_event, subject_hash
from app.modules.auth.schemas import UserProfile
from app.modules.auth.sessions import (
    SessionTokens,
    create_session,
    revoke,
    revoke_by_sid,
    rotate,
)

logger = logging.getLogger("app.auth.service")

INVALID_CREDENTIALS = "credenciales inválidas"
# Hash señuelo: el login con email inexistente verifica igual y no delata cuentas.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(24))


@dataclass(frozen=True, slots=True)
class LoginResult:
    """Sesión emitida: access + refresh (el refresh solo viaja en cookie)."""

    access_token: str
    expires_in: int
    refresh_token: str
    profile: UserProfile


class AuthService:
    """Casos de uso de identidad para el personal de la clínica."""

    def __init__(self, session: AsyncSession, redis: Redis, settings: Settings) -> None:
        self.session = session
        self.redis = redis
        self.settings = settings

    # ------------------------------------------------------------------ login

    async def login(self, email: str, password: str) -> LoginResult:
        """Autentica credenciales y crea una familia de refresh en Redis."""
        email_norm = email.strip().lower()
        candidatos = (
            (await self.session.execute(select(User).where(User.email == email_norm)))
            .scalars()
            .all()
        )
        user = candidatos[0] if len(candidatos) == 1 else None
        hash_a_verificar = user.password_hash if user is not None else _DUMMY_HASH
        password_ok = verify_password(password, hash_a_verificar)

        if user is None or not user.active or not password_ok:
            razon = "bad_password" if user is None or not password_ok else "inactive"
            await self._audit_login_failed(email_norm, user, razon)
            raise DomainError(401, INVALID_CREDENTIALS)

        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        user.last_login_at = utcnow()
        await self.session.flush()

        tokens = await self._create_session(user)
        access, expires_in = encode_access_token(
            user_id=user.id,
            clinic_id=user.clinic_id,
            roles=[user.role],
            email=user.email,
            sid=tokens.sid,
            settings=self.settings,
        )
        await record_best_effort(
            self.session,
            clinic_id=user.clinic_id,
            event=AuthEventType.LOGIN_SUCCESS,
            user_id=user.id,
            payload={"reason": "ok"},
        )
        await self.session.commit()
        return LoginResult(
            access_token=access,
            expires_in=expires_in,
            refresh_token=tokens.refresh_token,
            profile=_profile_from_user(user),
        )

    async def _audit_login_failed(self, email_norm: str, user: User | None, razon: str) -> None:
        """Audita `login_failed` sin bloquear la respuesta ni guardar el email."""
        clinic_id = user.clinic_id if user is not None else await self._single_clinic_id()
        if clinic_id is None:
            # Sin tenant deducible (DB de tests con varias clínicas): la traza no
            # puede inventar `clinic_id`; la respuesta sigue siendo genérica.
            return
        await record_best_effort(
            self.session,
            clinic_id=clinic_id,
            event=AuthEventType.LOGIN_FAILED,
            user_id=user.id if user is not None else None,
            subject_hash=subject_hash(email_norm),
            payload={"reason": razon},
        )

    async def _single_clinic_id(self) -> uuid.UUID | None:
        """Clínica única de la base (DD-07); `None` si hay cero o varias."""
        ids = (await self.session.execute(select(Clinic.id).limit(2))).scalars().all()
        return ids[0] if len(ids) == 1 else None

    async def _create_session(self, user: User) -> SessionTokens:
        try:
            return await create_session(
                self.redis,
                user_id=user.id,
                clinic_id=user.clinic_id,
                ttl_s=self.settings.JWT_REFRESH_DAYS * 86400,
            )
        except RedisError:
            raise DomainError(503, "auth_unavailable") from None

    # ---------------------------------------------------------------- refresh

    async def refresh(self, refresh_token: str) -> LoginResult:
        """Rota el refresh y emite un access nuevo; el reuso revoca la familia."""
        try:
            resultado = await rotate(self.redis, refresh_token)
        except RedisError:
            raise DomainError(503, "auth_unavailable") from None

        if resultado.status == "reuse":
            if resultado.clinic_id is not None:
                await record_best_effort(
                    self.session,
                    clinic_id=resultado.clinic_id,
                    event=AuthEventType.REFRESH_REUSE_DETECTED,
                    user_id=resultado.user_id,
                    payload={"generation": resultado.generation},
                )
                await self.session.commit()
            raise DomainError(401, "refresh_reuse")

        if resultado.status != "rotated" or resultado.user_id is None:
            raise DomainError(401, "invalid_refresh")
        if resultado.refresh_token is None:
            raise DomainError(401, "invalid_refresh")

        user = (
            await self.session.execute(
                select(User).where(
                    User.id == resultado.user_id,
                    User.clinic_id == resultado.clinic_id,
                )
            )
        ).scalar_one_or_none()
        if user is None or not user.active:
            await self._revoke(resultado.user_id, _sid_of(refresh_token))
            raise DomainError(401, "invalid_refresh")

        access, expires_in = encode_access_token(
            user_id=user.id,
            clinic_id=user.clinic_id,
            roles=[user.role],
            email=user.email,
            sid=_sid_of(refresh_token),
            settings=self.settings,
        )
        return LoginResult(
            access_token=access,
            expires_in=expires_in,
            refresh_token=resultado.refresh_token,
            profile=_profile_from_user(user),
        )

    # ----------------------------------------------------------------- logout

    async def logout(self, authorization: str | None, refresh_token: str | None) -> None:
        """Revoca la sesión del portador; idempotente (204 aunque ya no exista)."""
        sid: str | None = None
        user_id: uuid.UUID | None = None
        clinic_id: uuid.UUID | None = None

        token = _bearer_of(authorization)
        if token is not None:
            try:
                claims = decode_access_token(token, self.settings)
            except TokenError:
                claims = None
            if claims is not None:
                sid = claims.sid
                user_id = claims.user_id
                clinic_id = claims.clinic_id

        if sid is None and refresh_token:
            try:
                resultado = await rotate(self.redis, refresh_token)
            except RedisError:
                raise DomainError(503, "auth_unavailable") from None
            if resultado.status in ("rotated", "reuse"):
                sid = _sid_of(refresh_token)
                user_id = resultado.user_id
                clinic_id = resultado.clinic_id

        if sid is not None:
            try:
                await revoke_by_sid(self.redis, sid)
            except RedisError:
                raise DomainError(503, "auth_unavailable") from None
            if clinic_id is not None:
                await record_best_effort(
                    self.session,
                    clinic_id=clinic_id,
                    event=AuthEventType.LOGOUT,
                    user_id=user_id,
                    payload={"reason": "user_logout"},
                )
                await self.session.commit()

    # -------------------------------------------------------- change password

    async def change_password(
        self, principal: Principal, current_password: str, new_password: str
    ) -> None:
        """Cambia la clave propia, limpia el flag y revoca las demás sesiones."""
        user = (
            await self.session.execute(
                select(User).where(
                    User.id == principal.user_id,
                    User.clinic_id == principal.clinic_id,
                )
            )
        ).scalar_one_or_none()
        if user is None:
            raise DomainError(401, "invalid_session")
        if not verify_password(current_password, user.password_hash):
            raise DomainError(401, "invalid_credentials")
        if verify_password(new_password, user.password_hash):
            raise DomainError(422, "password_unchanged")

        user.password_hash = hash_password(new_password)
        user.password_changed_at = utcnow()
        user.must_change_password = False
        await self.session.flush()
        await record_event(
            self.session,
            clinic_id=user.clinic_id,
            event=AuthEventType.PASSWORD_CHANGED,
            user_id=user.id,
            actor_user_id=principal.user_id,
            payload={"reason": "self_service"},
        )

        try:
            miembros = await cast(
                Awaitable[set[str]],
                self.redis.smembers(f"auth:user:{user.id}"),
            )
            for sid in {str(sid) for sid in miembros} - {principal.sid}:
                await revoke(self.redis, sid, user.id)
        except RedisError:
            raise DomainError(503, "auth_unavailable") from None
        await self.session.commit()

    # ------------------------------------------------------------------ perfil

    async def profile(self, principal: Principal) -> UserProfile:
        """Perfil del portador con columnas explícitas (sin `password_hash`)."""
        row = (
            await self.session.execute(
                select(
                    User.id,
                    User.email,
                    User.role,
                    User.clinic_id,
                    User.professional_id,
                    User.must_change_password,
                    User.last_login_at,
                ).where(
                    User.id == principal.user_id,
                    User.clinic_id == principal.clinic_id,
                )
            )
        ).one_or_none()
        if row is None:
            raise DomainError(401, "invalid_session")
        return UserProfile(
            id=row.id,
            email=str(row.email),
            role=row.role,
            clinic_id=row.clinic_id,
            professional_id=row.professional_id,
            must_change_password=bool(row.must_change_password),
            last_login_at=row.last_login_at,
        )

    async def _revoke(self, user_id: uuid.UUID, sid: str) -> None:
        try:
            await revoke(self.redis, sid, user_id)
        except RedisError:
            raise DomainError(503, "auth_unavailable") from None


def _sid_of(refresh_token: str) -> str:
    return refresh_token.partition(".")[0]


def _bearer_of(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


def _profile_from_user(user: User) -> UserProfile:
    return UserProfile(
        id=user.id,
        email=user.email,
        role=user.role,
        clinic_id=user.clinic_id,
        professional_id=user.professional_id,
        must_change_password=user.must_change_password,
        last_login_at=user.last_login_at,
    )
