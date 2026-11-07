"""Router del dominio reminders: timeline, reenvío manual y seguimiento (C-11).

Routers finos → servicios. RBAC (`03_actores_y_roles.md`): admin, recepción y odontólogo leen el
timeline (el odontólogo, solo sus turnos; ajeno → `404`); solo admin y recepción reenvían y ven
el seguimiento (`403 forbidden_role` para el odontólogo).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.clock import get_now
from app.common.dependencies import require_roles
from app.common.principal import Principal
from app.core.deps import get_db
from app.core.settings import Settings, get_settings
from app.models import ReminderChannel, UserRole
from app.modules.appointments.audit import Actor
from app.modules.reminders.followup import follow_up
from app.modules.reminders.manual import resend
from app.modules.reminders.schemas import (
    FollowUpPage,
    RemindersStub,
    ResendAccepted,
    ResendRequest,
    TimelineRead,
)
from app.modules.reminders.service import RemindersService
from app.modules.reminders.timeline import build_timeline

router = APIRouter(tags=["reminders"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
Now = Annotated[datetime, Depends(get_now)]
AppSettings = Annotated[Settings, Depends(get_settings)]
FrontDeskDep = Annotated[Principal, Depends(require_roles(UserRole.ADMIN, UserRole.RECEPCION))]
StaffDep = Annotated[
    Principal,
    Depends(require_roles(UserRole.ADMIN, UserRole.RECEPCION, UserRole.ODONTOLOGO)),
]


@router.get("/reminders/ping", response_model=RemindersStub)
async def ping() -> RemindersStub:
    """Stub de cableado (routers finos → servicios)."""
    service = RemindersService()
    return RemindersStub(ping=await service.ping())


@router.get("/api/appointments/{appointment_id}/reminders", response_model=TimelineRead)
async def appointment_reminders(
    appointment_id: uuid.UUID,
    principal: StaffDep,
    session: DbSession,
    now: Now,
    settings: AppSettings,
) -> TimelineRead:
    """Timeline de recordatorios del turno por paso y canal (US-032 CA-1)."""
    return await build_timeline(
        session, Actor.from_principal(principal), appointment_id, now=now, settings=settings
    )


@router.post(
    "/api/appointments/{appointment_id}/reminders/{step}/{channel}/resend",
    response_model=ResendAccepted,
    status_code=202,
)
async def resend_reminder(
    appointment_id: uuid.UUID,
    step: str,
    channel: ReminderChannel,
    principal: FrontDeskDep,
    session: DbSession,
    now: Now,
    settings: AppSettings,
    payload: ResendRequest | None = None,
) -> ResendAccepted:
    """Reencola un recordatorio ya intentado; el worker lo envía (US-032 CA-2)."""
    return await resend(
        session,
        Actor.from_principal(principal),
        appointment_id,
        step,
        channel,
        payload.note if payload else None,
        now=now,
        settings=settings,
    )


@router.get("/api/reminders/follow-up", response_model=FollowUpPage)
async def reminders_follow_up(
    principal: FrontDeskDep,
    session: DbSession,
    now: Now,
    desde: Annotated[AwareDatetime, Query(alias="from")],
    hasta: Annotated[AwareDatetime, Query(alias="to")],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> FollowUpPage:
    """Turnos sin confirmar o con fallos de envío en `[from, to)` (US-032 CA-3)."""
    return await follow_up(session, principal.clinic_id, desde, hasta, cursor, limit, now=now)
