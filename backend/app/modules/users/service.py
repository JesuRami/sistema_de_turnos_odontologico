"""Servicio de gestión de usuarios del personal (C-03).

Todo filtro usa el `clinic_id` del principal (regla 4). La baja es lógica
(`active=false`, regla 7) y revoca sesiones. Las mutaciones y su evento de
auditoría se confirman en la misma transacción (RN-GL-01).
"""

from __future__ import annotations

import uuid
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import Select, and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import DomainError
from app.common.pagination import decode_cursor, encode_cursor
from app.common.principal import Principal
from app.core.jwt import utcnow
from app.core.security import hash_password
from app.core.settings import Settings
from app.models import AuthEventType, Professional, User, UserRole
from app.modules.auth.audit import record_event
from app.modules.auth.sessions import revoke_all
from app.modules.users.schemas import UserCreate, UserPage, UserRead, UserUpdate

_INVALID_USER = "Datos de usuario inválidos"
_INVALID_PROFESSIONAL = "Profesional inválido para la clínica"
_LAST_ADMIN = "La clínica no puede quedar sin administrador activo"

_USER_COLUMNS = (
    User.id,
    User.email,
    User.role,
    User.active,
    User.must_change_password,
    User.professional_id,
    User.last_login_at,
    User.created_at,
)


async def create_staff_user(
    session: AsyncSession,
    clinic_id: uuid.UUID,
    email: str,
    password: str,
    role: UserRole,
    professional_id: uuid.UUID | None = None,
    must_change_password: bool = True,
) -> User:
    """Crea un usuario del personal: email en minúsculas, contraseña como hash argon2id.

    Ante cualquier violación de constraint lanza `DomainError(422)` sin datos personales.
    """
    user = User(
        clinic_id=clinic_id,
        email=email.strip().lower(),
        password_hash=hash_password(password),
        role=role,
        professional_id=professional_id,
        must_change_password=must_change_password,
    )
    try:
        async with session.begin_nested():
            session.add(user)
            await session.flush()
    except IntegrityError:
        raise DomainError(422, _INVALID_USER) from None
    return user


async def get_user_by_email(session: AsyncSession, clinic_id: uuid.UUID, email: str) -> User | None:
    """Usuario de la clínica con ese email (insensible a mayúsculas) o `None`."""
    stmt = select(User).where(User.clinic_id == clinic_id, User.email == email.strip().lower())
    return (await session.execute(stmt)).scalar_one_or_none()


def _read(user: User) -> UserRead:
    return UserRead(
        id=user.id,
        email=user.email,
        role=user.role,
        active=user.active,
        must_change_password=user.must_change_password,
        professional_id=user.professional_id,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


class UsersService:
    """Casos de uso administrativos sobre el personal de una clínica."""

    def __init__(
        self,
        session: AsyncSession,
        redis: Redis,
        settings: Settings,
        principal: Principal,
    ) -> None:
        self.session = session
        self.redis = redis
        self.settings = settings
        self.principal = principal

    # --------------------------------------------------------------- helpers

    async def _get_in_clinic(self, user_id: uuid.UUID) -> User:
        user = (
            await self.session.execute(
                select(User).where(User.id == user_id, User.clinic_id == self.principal.clinic_id)
            )
        ).scalar_one_or_none()
        if user is None:
            raise DomainError(404, "not_found")
        return user

    async def _assert_professional(self, professional_id: uuid.UUID | None) -> None:
        """El profesional debe existir en la clínica del principal (sin filtrar B)."""
        if professional_id is None:
            return
        encontrado = await self.session.scalar(
            select(Professional.id).where(
                Professional.id == professional_id,
                Professional.clinic_id == self.principal.clinic_id,
            )
        )
        if encontrado is None:
            raise DomainError(422, _INVALID_PROFESSIONAL)

    async def _revoke_sessions(self, user_id: uuid.UUID) -> None:
        try:
            await revoke_all(self.redis, user_id)
        except RedisError:
            raise DomainError(503, "auth_unavailable") from None

    # ----------------------------------------------------------------- altas

    async def create(self, payload: UserCreate) -> UserRead:
        """Crea un usuario con clave provisoria y audita `user_created`."""
        await self._assert_professional(payload.professional_id)
        user = await create_staff_user(
            self.session,
            self.principal.clinic_id,
            payload.email,
            payload.password.get_secret_value(),
            payload.role,
            payload.professional_id,
        )
        await record_event(
            self.session,
            clinic_id=self.principal.clinic_id,
            event=AuthEventType.USER_CREATED,
            user_id=user.id,
            actor_user_id=self.principal.user_id,
            payload={"role": user.role.value},
        )
        await self.session.commit()
        return _read(user)

    # --------------------------------------------------------------- listado

    async def list(self, cursor: str | None, limit: int) -> UserPage:
        """Página por cursor de la clínica del principal, sin `password_hash`."""
        stmt: Select[Any] = select(*_USER_COLUMNS).where(User.clinic_id == self.principal.clinic_id)
        if cursor:
            ts, ultimo_id = decode_cursor(cursor)
            stmt = stmt.where(
                or_(
                    User.created_at > ts,
                    and_(User.created_at == ts, User.id > ultimo_id),
                )
            )
        stmt = stmt.order_by(User.created_at, User.id).limit(limit + 1)

        filas = (await self.session.execute(stmt)).all()
        hay_mas = len(filas) > limit
        visibles = filas[:limit]
        items = [
            UserRead(
                id=fila.id,
                email=str(fila.email),
                role=fila.role,
                active=bool(fila.active),
                must_change_password=bool(fila.must_change_password),
                professional_id=fila.professional_id,
                last_login_at=fila.last_login_at,
                created_at=fila.created_at,
            )
            for fila in visibles
        ]
        siguiente = (
            encode_cursor(visibles[-1].created_at, visibles[-1].id)
            if hay_mas and visibles
            else None
        )
        return UserPage(items=items, next_cursor=siguiente)

    # --------------------------------------------------------------- cambios

    async def update(self, user_id: uuid.UUID, payload: UserUpdate) -> UserRead:
        """Aplica cambios parciales, protege al último admin y revoca sesiones."""
        user = await self._get_in_clinic(user_id)
        campos = payload.model_fields_set

        nuevo_rol = payload.role if "role" in campos and payload.role else user.role
        nuevo_profesional = (
            payload.professional_id if "professional_id" in campos else user.professional_id
        )
        nuevo_active = payload.active if "active" in campos else user.active
        if nuevo_active is None:
            nuevo_active = user.active

        if nuevo_rol is UserRole.ODONTOLOGO and nuevo_profesional is None:
            raise DomainError(422, _INVALID_PROFESSIONAL)
        if "professional_id" in campos:
            await self._assert_professional(payload.professional_id)

        quita_admin = (
            user.role is UserRole.ADMIN
            and user.active
            and (nuevo_rol is not UserRole.ADMIN or not nuevo_active)
        )
        if quita_admin and await self._active_admins_count() <= 1:
            raise DomainError(409, _LAST_ADMIN)

        eventos: list[AuthEventType] = []
        usuario_cambio = False
        if "email" in campos and payload.email is not None and payload.email != user.email:
            user.email = payload.email
            usuario_cambio = True
        if "professional_id" in campos and nuevo_profesional != user.professional_id:
            user.professional_id = nuevo_profesional
            usuario_cambio = True
        if "role" in campos and payload.role is not None and payload.role is not user.role:
            anterior = user.role
            user.role = payload.role
            eventos.append(AuthEventType.ROLE_CHANGED)
            await record_event(
                self.session,
                clinic_id=user.clinic_id,
                event=AuthEventType.ROLE_CHANGED,
                user_id=user.id,
                actor_user_id=self.principal.user_id,
                payload={"from_role": anterior.value, "to_role": user.role.value},
            )
        if "active" in campos and payload.active is not None and payload.active != user.active:
            user.active = payload.active
            if not payload.active:
                eventos.append(AuthEventType.USER_DEACTIVATED)
                await record_event(
                    self.session,
                    clinic_id=user.clinic_id,
                    event=AuthEventType.USER_DEACTIVATED,
                    user_id=user.id,
                    actor_user_id=self.principal.user_id,
                    payload={"reason": "admin"},
                )
            else:
                usuario_cambio = True

        if usuario_cambio and AuthEventType.ROLE_CHANGED not in eventos:
            eventos.append(AuthEventType.USER_UPDATED)
            await record_event(
                self.session,
                clinic_id=user.clinic_id,
                event=AuthEventType.USER_UPDATED,
                user_id=user.id,
                actor_user_id=self.principal.user_id,
                payload={"fields": sorted(campos)},
            )

        if AuthEventType.ROLE_CHANGED in eventos or AuthEventType.USER_DEACTIVATED in eventos:
            await self._revoke_sessions(user.id)

        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            raise DomainError(422, _INVALID_USER) from None
        await self.session.refresh(user)
        return _read(user)

    async def _active_admins_count(self) -> int:
        """Cuenta admins activos bloqueando las filas (evita carrera de dos bajas)."""
        ids = (
            (
                await self.session.execute(
                    select(User.id)
                    .where(
                        User.clinic_id == self.principal.clinic_id,
                        User.role == UserRole.ADMIN,
                        User.active.is_(True),
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        return len(ids)

    # ------------------------------------------------------- reseteo de clave

    async def reset_password(self, user_id: uuid.UUID, new_password: str) -> None:
        """Fija clave provisoria, revoca sesiones y audita `password_changed`."""
        user = await self._get_in_clinic(user_id)
        user.password_hash = hash_password(new_password)
        user.must_change_password = True
        user.password_changed_at = utcnow()
        await self.session.flush()
        await record_event(
            self.session,
            clinic_id=user.clinic_id,
            event=AuthEventType.PASSWORD_CHANGED,
            user_id=user.id,
            actor_user_id=self.principal.user_id,
            payload={"reason": "admin_reset"},
        )
        await self._revoke_sessions(user.id)
        await self.session.commit()
