"""Router de gestión de usuarios (C-03): solo `admin` (prefijo `/api/users`)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import require_roles
from app.common.principal import Principal
from app.core.deps import get_db
from app.core.redis import get_redis
from app.core.settings import Settings, get_settings
from app.models import UserRole
from app.modules.users.schemas import (
    PasswordReset,
    UserCreate,
    UserPage,
    UserRead,
    UserUpdate,
)
from app.modules.users.service import UsersService

router = APIRouter(prefix="/api/users", tags=["users"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
RedisDep = Annotated[Redis, Depends(get_redis)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
AdminDep = Annotated[Principal, Depends(require_roles(UserRole.ADMIN))]


def _service(
    session: AsyncSession,
    redis: Redis,
    settings: Settings,
    principal: Principal,
) -> UsersService:
    return UsersService(session, redis, settings, principal)


@router.get("", response_model=UserPage)
async def list_users(
    admin: AdminDep,
    session: DbSession,
    redis: RedisDep,
    settings: SettingsDep,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> UserPage:
    """Listado por cursor, solo de la clínica del principal y sin secretos."""
    return await _service(session, redis, settings, admin).list(cursor, limit)


@router.post("", response_model=UserRead, status_code=201)
async def create_user(
    payload: UserCreate,
    admin: AdminDep,
    session: DbSession,
    redis: RedisDep,
    settings: SettingsDep,
) -> UserRead:
    """Alta de personal con clave provisoria; `clinic_id` sale del principal."""
    return await _service(session, redis, settings, admin).create(payload)


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    admin: AdminDep,
    session: DbSession,
    redis: RedisDep,
    settings: SettingsDep,
) -> UserRead:
    """Cambios parciales; la baja es lógica y revoca sesiones."""
    return await _service(session, redis, settings, admin).update(user_id, payload)


@router.post("/{user_id}/password-reset", status_code=204)
async def reset_password(
    user_id: uuid.UUID,
    payload: PasswordReset,
    admin: AdminDep,
    session: DbSession,
    redis: RedisDep,
    settings: SettingsDep,
) -> Response:
    """Fija una clave provisoria, revoca sesiones y no devuelve secretos."""
    await _service(session, redis, settings, admin).reset_password(
        user_id, payload.new_password.get_secret_value()
    )
    return Response(status_code=204)
