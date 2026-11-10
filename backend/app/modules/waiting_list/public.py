"""Link público de una oferta de la lista de espera: `/api/waitlist-offer/{token}` (C-12, D6).

Sin sesión ni `Principal`: la credencial firmada identifica UNA oferta y todo se resuelve bajo su
clínica (regla 4). Cualquier credencial inválida, de otro tipo, de una oferta inexistente o
vencida para lectura (`ends_at + MANAGE_TOKEN_TTL_H`) responde el mismo `404 offer_not_found`.
Cupos por IP y por SHA-256 del token (Redis nunca ve el token); respuestas `no-store` y
`no-referrer`. Ni el token ni datos del paciente van a logs, eventos ni errores.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, Request, Response
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.clock import get_now
from app.common.exceptions import PRIVATE_HEADERS, DomainError
from app.common.rate_limit_guard import consume
from app.common.request_meta import client_ip
from app.core.deps import get_db
from app.core.rate_limit import (
    waitlist_offer_read_ip_key,
    waitlist_offer_read_token_key,
    waitlist_offer_write_ip_key,
    waitlist_offer_write_token_key,
)
from app.core.redis import get_redis
from app.core.settings import Settings, get_settings
from app.models import (
    ActorType,
    Appointment,
    Clinic,
    Patient,
    Professional,
    WaitingListEntry,
    WaitlistOffer,
    WaitlistOfferStatus,
)
from app.modules.appointments.audit import Actor
from app.modules.reminders.links import build_manage_url
from app.modules.waiting_list.links import OFFER_TOKEN_RE, verify_offer_token
from app.modules.waiting_list.offers import OffersService
from app.modules.waiting_list.schemas import DeclineRequest

_UNAVAILABLE = "waitlist_offer_unavailable"
ViewStatus = Literal["pending", "accepted", "declined", "expired", "cancelled"]


class OfferAppointment(BaseModel):
    starts_at: datetime
    ends_at: datetime
    manage_url: str


class OfferView(BaseModel):
    """Lo que ve el paciente: datos públicos de la clínica, el hueco y el estado."""

    clinic_name: str
    clinic_phone: str | None
    timezone: str
    booking_url: str | None
    patient_first_name: str
    professional_name: str
    starts_at: datetime
    ends_at: datetime
    expires_at: datetime
    status: ViewStatus
    appointment: OfferAppointment | None


class OfferLinkService:
    def __init__(self, session: AsyncSession, now: datetime, settings: Settings) -> None:
        self.session = session
        self.now = now
        self.settings = settings

    def _offer_id(self, token: str) -> uuid.UUID:
        offer_id = verify_offer_token(self.settings.MANAGE_LINK_SECRET.get_secret_value(), token)
        if offer_id is None:
            raise DomainError(404, "offer_not_found")
        return offer_id

    async def _clinic_of(self, offer_id: uuid.UUID) -> uuid.UUID:
        fila = (
            await self.session.execute(
                select(WaitlistOffer.clinic_id, WaitlistOffer.ends_at).where(
                    WaitlistOffer.id == offer_id
                )
            )
        ).one_or_none()
        ttl = timedelta(hours=self.settings.MANAGE_TOKEN_TTL_H)
        if fila is None or self.now > fila.ends_at + ttl:
            raise DomainError(404, "offer_not_found")
        clinic_id: uuid.UUID = fila.clinic_id
        return clinic_id

    async def view(self, token: str) -> OfferView:
        offer_id = self._offer_id(token)
        await self._clinic_of(offer_id)
        return await self._view(offer_id)

    async def _view(self, offer_id: uuid.UUID) -> OfferView:
        fila = (
            await self.session.execute(
                select(
                    WaitlistOffer,
                    Clinic.name,
                    Clinic.contact_phone,
                    Clinic.timezone,
                    Clinic.slug,
                    Clinic.booking_enabled,
                    Patient.full_name,
                    Professional.display_name,
                )
                .join(Clinic, Clinic.id == WaitlistOffer.clinic_id)
                .join(
                    WaitingListEntry,
                    and_(
                        WaitingListEntry.clinic_id == WaitlistOffer.clinic_id,
                        WaitingListEntry.id == WaitlistOffer.entry_id,
                    ),
                )
                .join(
                    Patient,
                    and_(
                        Patient.clinic_id == WaitingListEntry.clinic_id,
                        Patient.id == WaitingListEntry.patient_id,
                    ),
                )
                .join(
                    Professional,
                    and_(
                        Professional.clinic_id == WaitlistOffer.clinic_id,
                        Professional.id == WaitlistOffer.professional_id,
                    ),
                )
                .where(WaitlistOffer.id == offer_id)
                .execution_options(populate_existing=True)
            )
        ).one()
        offer: WaitlistOffer = fila[0]
        estado: ViewStatus = offer.status.value
        if offer.status is WaitlistOfferStatus.PENDING and self.now >= offer.expires_at:
            estado = "expired"
        turno: OfferAppointment | None = None
        if offer.appointment_id is not None:
            horario = (
                await self.session.execute(
                    select(Appointment.starts_at, Appointment.ends_at).where(
                        Appointment.clinic_id == offer.clinic_id,
                        Appointment.id == offer.appointment_id,
                    )
                )
            ).one()
            turno = OfferAppointment(
                starts_at=horario.starts_at,
                ends_at=horario.ends_at,
                manage_url=build_manage_url(self.settings, offer.appointment_id),
            )
        base = self.settings.FRONTEND_PUBLIC_URL.rstrip("/")
        return OfferView(
            clinic_name=fila[1],
            clinic_phone=fila[2],
            timezone=fila[3],
            booking_url=f"{base}/b/{fila[4]}" if fila[5] else None,
            patient_first_name=(fila[6].split() or [""])[0],
            professional_name=fila[7],
            starts_at=offer.starts_at,
            ends_at=offer.ends_at,
            expires_at=offer.expires_at,
            status=estado,
            appointment=turno,
        )

    async def _service(self, offer_id: uuid.UUID) -> OffersService:
        clinic_id = await self._clinic_of(offer_id)
        actor = Actor(clinic_id=clinic_id, type=ActorType.PATIENT_TOKEN)
        return OffersService(self.session, actor, self.now, self.settings)

    async def accept(self, token: str) -> OfferView:
        offer_id = self._offer_id(token)
        await (await self._service(offer_id)).accept(offer_id)
        return await self._view(offer_id)

    async def decline(self, token: str, *, leave_list: bool) -> OfferView:
        offer_id = self._offer_id(token)
        await (await self._service(offer_id)).decline(offer_id, leave_list=leave_list)
        return await self._view(offer_id)


# ----------------------------------------------------------------------------- router


def private_headers(response: Response) -> None:
    response.headers.update(PRIVATE_HEADERS)


router = APIRouter(
    prefix="/api/waitlist-offer",
    tags=["waitlist_offer"],
    dependencies=[Depends(private_headers)],
)

DbSession = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
Now = Annotated[datetime, Depends(get_now)]
RedisDep = Annotated[Redis, Depends(get_redis)]


async def _consume_token(redis: Redis, token: str, key: Callable[[str], str], spec: str) -> None:
    """Cupo por token (su SHA-256); un token malformado no crea claves: lo frena el cupo por IP."""
    if OFFER_TOKEN_RE.match(token):
        huella = hashlib.sha256(token.encode()).hexdigest()
        await consume(redis, key(huella), spec, unavailable_code=_UNAVAILABLE)


async def limit_reads(token: str, request: Request, redis: RedisDep, settings: SettingsDep) -> None:
    await consume(
        redis,
        waitlist_offer_read_ip_key(client_ip(request)),
        settings.MANAGE_READ_IP_RATE_LIMIT,
        unavailable_code=_UNAVAILABLE,
    )
    await _consume_token(
        redis, token, waitlist_offer_read_token_key, settings.MANAGE_READ_TOKEN_RATE_LIMIT
    )


async def limit_writes(
    token: str, request: Request, redis: RedisDep, settings: SettingsDep
) -> None:
    """Se consumen ANTES de validar el cuerpo: un 422 también gasta cupo."""
    await consume(
        redis,
        waitlist_offer_write_ip_key(client_ip(request)),
        settings.MANAGE_WRITE_IP_RATE_LIMIT,
        unavailable_code=_UNAVAILABLE,
    )
    await _consume_token(
        redis, token, waitlist_offer_write_token_key, settings.MANAGE_WRITE_TOKEN_RATE_LIMIT
    )


@router.get("/{token}", response_model=OfferView, dependencies=[Depends(limit_reads)])
async def view_offer(token: str, session: DbSession, now: Now, settings: SettingsDep) -> OfferView:
    """Hueco ofrecido, vencimiento y estado, con los datos públicos de la clínica."""
    return await OfferLinkService(session, now, settings).view(token)


@router.post("/{token}/accept", response_model=OfferView, dependencies=[Depends(limit_writes)])
async def accept_offer(
    token: str, session: DbSession, now: Now, settings: SettingsDep
) -> OfferView:
    return await OfferLinkService(session, now, settings).accept(token)


@router.post("/{token}/decline", response_model=OfferView, dependencies=[Depends(limit_writes)])
async def decline_offer(
    token: str,
    session: DbSession,
    now: Now,
    settings: SettingsDep,
    payload: Annotated[DeclineRequest | None, Body()] = None,
) -> OfferView:
    return await OfferLinkService(session, now, settings).decline(
        token, leave_list=bool(payload and payload.leave_list)
    )
