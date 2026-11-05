"""Router público de gestión por token (C-08, D1). Fino: cabeceras, rate-limit y traducción HTTP.

Sin `Principal` ni sesión: la clínica y el turno se resuelven solo por el token. Ninguna
respuesta se cachea ni filtra su URL (`no-store`, `no-referrer`); los errores reciben las
mismas cabeceras desde `app.common.exceptions`. Este módulo no loguea el path ni el token.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query, Request, Response
from pydantic import AwareDatetime
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.clock import get_now
from app.common.exceptions import PRIVATE_HEADERS
from app.common.rate_limit_guard import consume
from app.common.request_meta import client_ip
from app.core.deps import get_db
from app.core.rate_limit import (
    manage_read_ip_key,
    manage_read_token_key,
    manage_write_ip_key,
    manage_write_token_key,
)
from app.core.redis import get_redis
from app.core.settings import Settings, get_settings
from app.modules.manage.schemas import (
    CancelRequest,
    ManageAction,
    ManageAvailability,
    ManageView,
    RescheduleRequest,
)
from app.modules.manage.service import TOKEN_RE, ManageService
from app.modules.reminders.invalidation import (
    ReminderInvalidator,
    get_reminder_invalidator,
)


def private_headers(response: Response) -> None:
    response.headers.update(PRIVATE_HEADERS)


router = APIRouter(prefix="/api/manage", tags=["manage"], dependencies=[Depends(private_headers)])

DbSession = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
Now = Annotated[datetime, Depends(get_now)]
InvalidatorDep = Annotated[ReminderInvalidator, Depends(get_reminder_invalidator)]
RedisDep = Annotated[Redis, Depends(get_redis)]

_UNAVAILABLE = "manage_unavailable"


async def _consume_token(redis: Redis, token: str, key: Callable[[str], str], spec: str) -> None:
    """Cupo por token: la clave es el SHA-256 (Redis nunca ve el token). Un token malformado
    no consume ni crea claves: el barrido lo frena el cupo por IP."""
    if TOKEN_RE.match(token):
        huella = hashlib.sha256(token.encode()).hexdigest()
        await consume(redis, key(huella), spec, unavailable_code=_UNAVAILABLE)


async def limit_reads(token: str, request: Request, redis: RedisDep, settings: SettingsDep) -> None:
    """Lecturas (D10): IP antes de resolver el token; token antes de tocar la base."""
    await consume(
        redis,
        manage_read_ip_key(client_ip(request)),
        settings.MANAGE_READ_IP_RATE_LIMIT,
        unavailable_code=_UNAVAILABLE,
    )
    await _consume_token(redis, token, manage_read_token_key, settings.MANAGE_READ_TOKEN_RATE_LIMIT)


async def limit_writes(
    token: str, request: Request, redis: RedisDep, settings: SettingsDep
) -> None:
    """Escrituras (D10): se consumen ANTES de validar el cuerpo, así un 422 también gasta."""
    await consume(
        redis,
        manage_write_ip_key(client_ip(request)),
        settings.MANAGE_WRITE_IP_RATE_LIMIT,
        unavailable_code=_UNAVAILABLE,
    )
    await _consume_token(
        redis, token, manage_write_token_key, settings.MANAGE_WRITE_TOKEN_RATE_LIMIT
    )


@router.get("/{token}", response_model=ManageView, dependencies=[Depends(limit_reads)])
async def view(token: str, session: DbSession, now: Now, settings: SettingsDep) -> ManageView:
    """Vista de gestión del turno del token (datos mínimos y acciones habilitadas)."""
    return await ManageService(session, now, settings).view(token)


@router.get(
    "/{token}/availability",
    response_model=ManageAvailability,
    dependencies=[Depends(limit_reads)],
)
async def availability(
    token: str,
    session: DbSession,
    now: Now,
    settings: SettingsDep,
    desde: Annotated[AwareDatetime, Query(alias="from")],
    hasta: Annotated[AwareDatetime, Query(alias="to")],
) -> ManageAvailability:
    """Huecos del mismo profesional para reprogramar en `[from, to)` (≤ 14 días)."""
    return await ManageService(session, now, settings).availability(token, desde, hasta)


@router.patch("/{token}", response_model=ManageView, dependencies=[Depends(limit_writes)])
async def act(
    token: str,
    payload: Annotated[ManageAction, Body(discriminator="action")],
    session: DbSession,
    now: Now,
    settings: SettingsDep,
    invalidator: InvalidatorDep,
) -> ManageView:
    """Una acción del paciente sobre su turno; devuelve la vista actualizada."""
    service = ManageService(session, now, settings, invalidator)
    if isinstance(payload, CancelRequest):
        return await service.cancel(token, payload)
    if isinstance(payload, RescheduleRequest):
        return await service.reschedule(token, payload)
    return await service.confirm(token)
