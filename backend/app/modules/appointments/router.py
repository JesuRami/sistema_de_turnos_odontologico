"""Router de turnos (C-05). Routers finos → `AppointmentsService`.

RBAC (`03_actores_y_roles.md` §Matriz): admin y recepción crean, reprograman y
cancelan; el odontólogo lee y marca asistencia solo de sus turnos (alcance en
SQL, ajeno → `404`). El historial de eventos es solo para admin. No existe
`DELETE`: la única baja es la cancelación con motivo (regla 7).
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
from app.models import AppointmentStatus, UserRole
from app.modules.appointments.audit import Actor
from app.modules.appointments.schemas import (
    AppointmentCreate,
    AppointmentEventList,
    AppointmentPage,
    AppointmentRead,
    AppointmentUpdate,
    TransitionRequest,
)
from app.modules.appointments.service import AppointmentsService

router = APIRouter(prefix="/api", tags=["appointments"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
Now = Annotated[datetime, Depends(get_now)]
AdminDep = Annotated[Principal, Depends(require_roles(UserRole.ADMIN))]
FrontDeskDep = Annotated[Principal, Depends(require_roles(UserRole.ADMIN, UserRole.RECEPCION))]
StaffDep = Annotated[
    Principal,
    Depends(require_roles(UserRole.ADMIN, UserRole.RECEPCION, UserRole.ODONTOLOGO)),
]


def _service(session: AsyncSession, principal: Principal, now: datetime) -> AppointmentsService:
    return AppointmentsService(session, Actor.from_principal(principal), now)


@router.get("/appointments", response_model=AppointmentPage)
async def list_appointments(
    principal: StaffDep,
    session: DbSession,
    now: Now,
    desde: Annotated[AwareDatetime, Query(alias="from")],
    hasta: Annotated[AwareDatetime, Query(alias="to")],
    professional_id: Annotated[uuid.UUID | None, Query()] = None,
    chair_id: Annotated[uuid.UUID | None, Query()] = None,
    status: Annotated[list[AppointmentStatus] | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> AppointmentPage:
    """Turnos que intersectan `[from, to)` (≤ 31 días); el odontólogo, solo los suyos."""
    return await _service(session, principal, now).list_range(
        desde, hasta, professional_id, chair_id, status, cursor, limit
    )


@router.get("/appointments/{appointment_id}", response_model=AppointmentRead)
async def get_appointment(
    appointment_id: uuid.UUID, principal: StaffDep, session: DbSession, now: Now
) -> AppointmentRead:
    """Un turno; ajeno al alcance del principal → `404`."""
    return await _service(session, principal, now).get(appointment_id)


@router.post("/appointments", response_model=AppointmentRead, status_code=201)
async def create_appointment(
    payload: AppointmentCreate, principal: FrontDeskDep, session: DbSession, now: Now
) -> AppointmentRead:
    """Alta desde recepción; colisión → `409 slot_taken` con alternativos."""
    return await _service(session, principal, now).create(payload)


@router.patch("/appointments/{appointment_id}", response_model=AppointmentRead)
async def update_appointment(
    appointment_id: uuid.UUID,
    payload: AppointmentUpdate,
    principal: FrontDeskDep,
    session: DbSession,
    now: Now,
) -> AppointmentRead:
    """Reprogramación atómica (RN-AG-06) y/o edición de notas operativas."""
    return await _service(session, principal, now).update(appointment_id, payload)


@router.post("/appointments/{appointment_id}/transitions", response_model=AppointmentRead)
async def transition_appointment(
    appointment_id: uuid.UUID,
    payload: TransitionRequest,
    principal: StaffDep,
    session: DbSession,
    now: Now,
) -> AppointmentRead:
    """Confirmar, presente, ausente, no-show o cancelar (máquina de estados D6)."""
    return await _service(session, principal, now).transition(appointment_id, payload)


@router.get("/appointments/{appointment_id}/events", response_model=AppointmentEventList)
async def appointment_events(
    appointment_id: uuid.UUID, admin: AdminDep, session: DbSession, now: Now
) -> AppointmentEventList:
    """Historial inmutable del turno en orden cronológico (solo admin)."""
    return await _service(session, admin, now).events(appointment_id)
