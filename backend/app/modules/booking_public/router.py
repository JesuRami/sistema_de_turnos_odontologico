"""Router público de reserva (C-07, D1). Fino: rate-limit, 404 uniformes y traducción HTTP.

Sin `Principal`: la clínica se resuelve solo por slug y todo se filtra por su `clinic_id`.
Las respuestas llevan `Cache-Control: no-store` (la disponibilidad cambia; la reserva lleva el
token de gestión).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import AwareDatetime
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.clock import get_now
from app.common.rate_limit_guard import consume
from app.common.request_meta import client_ip
from app.core.deps import get_db
from app.core.rate_limit import (
    booking_create_ip_key,
    booking_create_slug_key,
    booking_read_key,
    waitlist_join_ip_key,
    waitlist_join_slug_key,
)
from app.core.redis import get_redis
from app.core.settings import Settings, get_settings
from app.modules.booking_public.guard import BotGuard, get_bot_guard
from app.modules.booking_public.schemas import (
    AvailabilityRead,
    BookingCreate,
    BookingCreated,
    CatalogRead,
    WaitlistJoin,
    WaitlistJoined,
)
from app.modules.booking_public.service import BookingPublicService, PublicClinic

router = APIRouter(prefix="/api/booking", tags=["booking_public"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
RedisDep = Annotated[Redis, Depends(get_redis)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
Now = Annotated[datetime, Depends(get_now)]

_UNAVAILABLE = "booking_unavailable"


async def limit_reads(request: Request, redis: RedisDep, settings: SettingsDep) -> None:
    """Cupo de lecturas por IP, ANTES de resolver el slug: el barrido de slugs también se frena."""
    await consume(
        redis,
        booking_read_key(client_ip(request)),
        settings.PUBLIC_BOOKING_READ_RATE_LIMIT,
        unavailable_code=_UNAVAILABLE,
    )


def _service(session: AsyncSession, now: datetime, settings: Settings) -> BookingPublicService:
    return BookingPublicService(session, now, settings)


@router.get("/{slug}", response_model=CatalogRead, dependencies=[Depends(limit_reads)])
async def catalog(
    slug: str, response: Response, session: DbSession, now: Now, settings: SettingsDep
) -> CatalogRead:
    """Nombre, zona horaria y profesionales reservables (solo id y nombre visible)."""
    response.headers["Cache-Control"] = "no-store"
    service = _service(session, now, settings)
    return await service.catalog(await service.resolve_clinic(slug))


@router.get(
    "/{slug}/availability",
    response_model=AvailabilityRead,
    dependencies=[Depends(limit_reads)],
)
async def availability(
    slug: str,
    response: Response,
    session: DbSession,
    now: Now,
    settings: SettingsDep,
    professional_id: Annotated[uuid.UUID, Query()],
    desde: Annotated[AwareDatetime, Query(alias="from")],
    hasta: Annotated[AwareDatetime, Query(alias="to")],
) -> AvailabilityRead:
    """Huecos libres de un profesional reservable en `[from, to)` (≤ 14 días)."""
    response.headers["Cache-Control"] = "no-store"
    service = _service(session, now, settings)
    clinic = await service.resolve_clinic(slug)
    return await service.availability(clinic, professional_id, desde, hasta)


async def limit_create_by_ip(request: Request, redis: RedisDep, settings: SettingsDep) -> None:
    """Cupo de reservas por IP (RN-ON-03): se consume ANTES de validar el cuerpo (un 422 gasta)."""
    await consume(
        redis,
        booking_create_ip_key(client_ip(request)),
        settings.PUBLIC_BOOKING_IP_RATE_LIMIT,
        unavailable_code=_UNAVAILABLE,
    )


async def clinic_for_booking(
    slug: str, session: DbSession, redis: RedisDep, now: Now, settings: SettingsDep
) -> PublicClinic:
    """Resuelve la clínica por slug (404 uniforme) y recién entonces consume el cupo del slug."""
    clinic = await _service(session, now, settings).resolve_clinic(slug)
    await consume(
        redis,
        booking_create_slug_key(clinic.id),
        settings.PUBLIC_BOOKING_SLUG_RATE_LIMIT,
        unavailable_code=_UNAVAILABLE,
    )
    return clinic


async def verify_bot(request: Request, guard: Annotated[BotGuard, Depends(get_bot_guard)]) -> None:
    await guard.verify(request, action="book")


@router.post(
    "/{slug}/appointments",
    response_model=BookingCreated,
    status_code=201,
    dependencies=[Depends(limit_create_by_ip)],
)
async def create_booking(
    payload: BookingCreate,
    response: Response,
    clinic: Annotated[PublicClinic, Depends(clinic_for_booking)],
    _bot: Annotated[None, Depends(verify_bot)],
    session: DbSession,
    now: Now,
    settings: SettingsDep,
) -> BookingCreated:
    """Reserva sin cuenta: turno `pending` online, link de gestión de un solo uso de vista."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return await _service(session, now, settings).book(clinic, payload)


# ------------------------------------------------------------ lista de espera (C-12, D7)


async def limit_join_by_ip(request: Request, redis: RedisDep, settings: SettingsDep) -> None:
    """Cupo de anotaciones por IP, ANTES de validar el cuerpo (un 422 también gasta)."""
    await consume(
        redis,
        waitlist_join_ip_key(client_ip(request)),
        settings.WAITLIST_PUBLIC_IP_RATE_LIMIT,
        unavailable_code=_UNAVAILABLE,
    )


async def clinic_for_waitlist(
    slug: str, session: DbSession, redis: RedisDep, now: Now, settings: SettingsDep
) -> PublicClinic:
    """Clínica por slug (404 uniforme) y luego el cupo de anotaciones de esa clínica."""
    clinic = await _service(session, now, settings).resolve_clinic(slug)
    await consume(
        redis,
        waitlist_join_slug_key(clinic.id),
        settings.WAITLIST_PUBLIC_SLUG_RATE_LIMIT,
        unavailable_code=_UNAVAILABLE,
    )
    return clinic


@router.post(
    "/{slug}/waiting-list",
    response_model=WaitlistJoined,
    status_code=201,
    dependencies=[Depends(limit_join_by_ip)],
)
async def join_waitlist(
    payload: WaitlistJoin,
    response: Response,
    clinic: Annotated[PublicClinic, Depends(clinic_for_waitlist)],
    _bot: Annotated[None, Depends(verify_bot)],
    session: DbSession,
    now: Now,
    settings: SettingsDep,
) -> WaitlistJoined:
    """Anotación sin cuenta en la lista de espera de la clínica."""
    response.headers["Cache-Control"] = "no-store"
    return await _service(session, now, settings).join_waitlist(clinic, payload)
