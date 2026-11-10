"""Router de la lista de espera para el personal (C-12, D11). Routers finos → servicios.

RBAC (`03_actores_y_roles.md` §Matriz, Lista de espera): admin y recepción CRUD; el odontólogo
lee la cola de su profesional y de "cualquiera", sin contacto ni acciones. Las rutas fijas
(`/offers`) se declaran antes que `/{entry_id}`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query
from pydantic import AwareDatetime
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.clock import get_now
from app.common.dependencies import require_roles
from app.common.principal import Principal
from app.core.deps import get_db
from app.core.settings import Settings, get_settings
from app.models import UserRole, WaitingListStatus, WaitlistOfferStatus
from app.modules.appointments.audit import Actor
from app.modules.waiting_list.entries import EntriesService
from app.modules.waiting_list.offers import OffersService
from app.modules.waiting_list.schemas import (
    AcceptedOffer,
    DeclineRequest,
    EntryCreate,
    EntryPage,
    EntryRead,
    EntryUpdate,
    ManualOfferCreate,
    OfferPage,
    OfferRead,
    PriorityRequest,
    SlotList,
    WaitlistEventList,
)

router = APIRouter(prefix="/api/waiting-list", tags=["waiting_list"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
Now = Annotated[datetime, Depends(get_now)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
FrontDeskDep = Annotated[Principal, Depends(require_roles(UserRole.ADMIN, UserRole.RECEPCION))]
StaffDep = Annotated[
    Principal,
    Depends(require_roles(UserRole.ADMIN, UserRole.RECEPCION, UserRole.ODONTOLOGO)),
]


def _entries(
    session: AsyncSession, principal: Principal, now: datetime, settings: Settings
) -> EntriesService:
    return EntriesService(session, Actor.from_principal(principal), now, settings)


@router.get("", response_model=EntryPage)
async def list_entries(
    principal: StaffDep,
    session: DbSession,
    now: Now,
    settings: SettingsDep,
    status: Annotated[list[WaitingListStatus] | None, Query()] = None,
    professional_id: Annotated[uuid.UUID | None, Query()] = None,
    desde: Annotated[date | None, Query(alias="from")] = None,
    hasta: Annotated[date | None, Query(alias="to")] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> EntryPage:
    """Cola por prioridad y antigüedad, con filtros y cursor."""
    return await _entries(session, principal, now, settings).list(
        statuses=status,
        professional_id=professional_id,
        desde=desde,
        hasta=hasta,
        cursor=cursor,
        limit=limit,
    )


@router.post("", response_model=EntryRead, status_code=201)
async def create_entry(
    payload: EntryCreate,
    principal: FrontDeskDep,
    session: DbSession,
    now: Now,
    settings: SettingsDep,
) -> EntryRead:
    return await _entries(session, principal, now, settings).create(payload)


def _offers(
    session: AsyncSession, principal: Principal, now: datetime, settings: Settings
) -> OffersService:
    return OffersService(session, Actor.from_principal(principal), now, settings)


# ------------------------------------------------------------------ ofertas (rutas fijas)


@router.get("/offers", response_model=OfferPage)
async def list_offers(
    principal: FrontDeskDep,
    session: DbSession,
    now: Now,
    settings: SettingsDep,
    status: Annotated[list[WaitlistOfferStatus] | None, Query()] = None,
    desde: Annotated[AwareDatetime | None, Query(alias="from")] = None,
    hasta: Annotated[AwareDatetime | None, Query(alias="to")] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> OfferPage:
    """Ofertas de la clínica por estado y fecha de creación, más nuevas primero."""
    return await _offers(session, principal, now, settings).list(
        statuses=status, desde=desde, hasta=hasta, cursor=cursor, limit=limit
    )


@router.post("/offers/{offer_id}/accept", response_model=AcceptedOffer)
async def accept_offer(
    offer_id: uuid.UUID,
    principal: FrontDeskDep,
    session: DbSession,
    now: Now,
    settings: SettingsDep,
) -> AcceptedOffer:
    """Aceptar en nombre del paciente que llamó: crea el turno `waitlist`."""
    return await _offers(session, principal, now, settings).accept(offer_id)


@router.post("/offers/{offer_id}/decline", response_model=OfferRead)
async def decline_offer(
    offer_id: uuid.UUID,
    principal: FrontDeskDep,
    session: DbSession,
    now: Now,
    settings: SettingsDep,
    payload: Annotated[DeclineRequest | None, Body()] = None,
) -> OfferRead:
    return await _offers(session, principal, now, settings).decline(
        offer_id, leave_list=bool(payload and payload.leave_list)
    )


@router.post("/offers/{offer_id}/cancel", response_model=OfferRead)
async def cancel_offer(
    offer_id: uuid.UUID,
    principal: FrontDeskDep,
    session: DbSession,
    now: Now,
    settings: SettingsDep,
) -> OfferRead:
    """Retirar una oferta pendiente: la entrada vuelve a la cola y el hueco rota."""
    return await _offers(session, principal, now, settings).withdraw(offer_id)


# ------------------------------------------------------------------------ entradas


@router.get("/{entry_id}", response_model=EntryRead)
async def get_entry(
    entry_id: uuid.UUID, principal: StaffDep, session: DbSession, now: Now, settings: SettingsDep
) -> EntryRead:
    return await _entries(session, principal, now, settings).get(entry_id)


@router.patch("/{entry_id}", response_model=EntryRead)
async def update_entry(
    entry_id: uuid.UUID,
    payload: EntryUpdate,
    principal: FrontDeskDep,
    session: DbSession,
    now: Now,
    settings: SettingsDep,
) -> EntryRead:
    return await _entries(session, principal, now, settings).update(entry_id, payload)


@router.post("/{entry_id}/withdraw", response_model=EntryRead)
async def withdraw_entry(
    entry_id: uuid.UUID,
    principal: FrontDeskDep,
    session: DbSession,
    now: Now,
    settings: SettingsDep,
) -> EntryRead:
    return await _entries(session, principal, now, settings).withdraw(entry_id)


@router.post("/{entry_id}/priority", response_model=EntryRead)
async def prioritize_entry(
    entry_id: uuid.UUID,
    payload: PriorityRequest,
    principal: FrontDeskDep,
    session: DbSession,
    now: Now,
    settings: SettingsDep,
) -> EntryRead:
    return await _entries(session, principal, now, settings).prioritize(entry_id, payload.reason)


@router.delete("/{entry_id}/priority", response_model=EntryRead)
async def unprioritize_entry(
    entry_id: uuid.UUID,
    principal: FrontDeskDep,
    session: DbSession,
    now: Now,
    settings: SettingsDep,
) -> EntryRead:
    return await _entries(session, principal, now, settings).unprioritize(entry_id)


@router.get("/{entry_id}/events", response_model=WaitlistEventList)
async def entry_events(
    entry_id: uuid.UUID,
    principal: FrontDeskDep,
    session: DbSession,
    now: Now,
    settings: SettingsDep,
) -> WaitlistEventList:
    return await _entries(session, principal, now, settings).events(entry_id)


@router.get("/{entry_id}/slots", response_model=SlotList)
async def entry_slots(
    entry_id: uuid.UUID,
    principal: FrontDeskDep,
    session: DbSession,
    now: Now,
    settings: SettingsDep,
    desde: Annotated[AwareDatetime, Query(alias="from")],
    hasta: Annotated[AwareDatetime, Query(alias="to")],
) -> SlotList:
    """Huecos libres (≤ 14 días) que respetan las preferencias de la entrada."""
    return await _offers(session, principal, now, settings).slots(entry_id, desde, hasta)


@router.post("/{entry_id}/offers", response_model=OfferRead, status_code=201)
async def manual_offer(
    entry_id: uuid.UUID,
    payload: ManualOfferCreate,
    principal: FrontDeskDep,
    session: DbSession,
    now: Now,
    settings: SettingsDep,
) -> OfferRead:
    """Oferta manual de un hueco; saltear la cola exige `fifo_skip_reason` (D10)."""
    return await _offers(session, principal, now, settings).manual_offer(entry_id, payload)
