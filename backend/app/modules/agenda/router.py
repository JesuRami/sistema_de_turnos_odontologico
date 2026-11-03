"""Router de configuración de agenda (C-04): recursos, plantilla semanal y bloqueos.

Routers finos → servicios. RBAC según `03_actores_y_roles.md` §Matriz: la
configuración la escribe el admin; recepción y odontólogo leen (este último solo
lo propio, aplicado en SQL por el servicio).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import require_roles
from app.common.principal import Principal
from app.core.deps import get_db
from app.models import UserRole
from app.modules.agenda.blocks import BlocksService
from app.modules.agenda.schedules import SchedulesService
from app.modules.agenda.schemas import (
    BlockCreate,
    BlockList,
    BlockPage,
    BlockRead,
    BlockUpdate,
    ChairCreate,
    ChairPage,
    ChairRead,
    ChairUpdate,
    ClosureCreate,
    ProfessionalCreate,
    ProfessionalPage,
    ProfessionalRead,
    ProfessionalUpdate,
    ScheduleRuleCreate,
    ScheduleRulePage,
    ScheduleRuleRead,
    ScheduleRuleUpdate,
)
from app.modules.agenda.service import ResourcesService

router = APIRouter(prefix="/api", tags=["agenda"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
AdminDep = Annotated[Principal, Depends(require_roles(UserRole.ADMIN))]
StaffDep = Annotated[
    Principal,
    Depends(require_roles(UserRole.ADMIN, UserRole.RECEPCION, UserRole.ODONTOLOGO)),
]
Cursor = Annotated[str | None, Query()]
Limit = Annotated[int, Query(ge=1, le=200)]
ActiveFilter = Annotated[bool | None, Query()]


# ---------------------------------------------------------------- profesionales


@router.get("/professionals", response_model=ProfessionalPage)
async def list_professionals(
    principal: StaffDep,
    session: DbSession,
    active: ActiveFilter = None,
    cursor: Cursor = None,
    limit: Limit = 50,
) -> ProfessionalPage:
    """Profesionales de la clínica (el odontólogo solo recibe el suyo)."""
    return await ResourcesService(session, principal).list_professionals(active, cursor, limit)


@router.get("/professionals/{professional_id}", response_model=ProfessionalRead)
async def get_professional(
    professional_id: uuid.UUID, principal: StaffDep, session: DbSession
) -> ProfessionalRead:
    """Un profesional; ajeno al alcance del principal → `404`."""
    return await ResourcesService(session, principal).get_professional(professional_id)


@router.post("/professionals", response_model=ProfessionalRead, status_code=201)
async def create_professional(
    payload: ProfessionalCreate, admin: AdminDep, session: DbSession
) -> ProfessionalRead:
    """Alta de profesional en la clínica del admin."""
    return await ResourcesService(session, admin).create_professional(payload)


@router.patch("/professionals/{professional_id}", response_model=ProfessionalRead)
async def update_professional(
    professional_id: uuid.UUID,
    payload: ProfessionalUpdate,
    admin: AdminDep,
    session: DbSession,
) -> ProfessionalRead:
    """Edición parcial; `active=false` es la baja lógica."""
    return await ResourcesService(session, admin).update_professional(professional_id, payload)


# --------------------------------------------------------------------- sillones


@router.get("/chairs", response_model=ChairPage)
async def list_chairs(
    principal: StaffDep,
    session: DbSession,
    active: ActiveFilter = None,
    cursor: Cursor = None,
    limit: Limit = 50,
) -> ChairPage:
    """Sillones de la clínica (lectura para todo el personal)."""
    return await ResourcesService(session, principal).list_chairs(active, cursor, limit)


@router.get("/chairs/{chair_id}", response_model=ChairRead)
async def get_chair(chair_id: uuid.UUID, principal: StaffDep, session: DbSession) -> ChairRead:
    """Un sillón de la clínica."""
    return await ResourcesService(session, principal).get_chair(chair_id)


@router.post("/chairs", response_model=ChairRead, status_code=201)
async def create_chair(payload: ChairCreate, admin: AdminDep, session: DbSession) -> ChairRead:
    """Alta de sillón en la clínica del admin."""
    return await ResourcesService(session, admin).create_chair(payload)


@router.patch("/chairs/{chair_id}", response_model=ChairRead)
async def update_chair(
    chair_id: uuid.UUID, payload: ChairUpdate, admin: AdminDep, session: DbSession
) -> ChairRead:
    """Edición parcial; `active=false` es la baja lógica."""
    return await ResourcesService(session, admin).update_chair(chair_id, payload)


# ------------------------------------------------------------ plantilla semanal


@router.get("/schedules", response_model=ScheduleRulePage)
async def list_schedules(
    principal: StaffDep,
    session: DbSession,
    professional_id: Annotated[uuid.UUID | None, Query()] = None,
    chair_id: Annotated[uuid.UUID | None, Query()] = None,
    active: ActiveFilter = None,
    cursor: Cursor = None,
    limit: Limit = 50,
) -> ScheduleRulePage:
    """Reglas semanales (el odontólogo solo recibe las propias)."""
    return await SchedulesService(session, principal).list(
        professional_id, chair_id, active, cursor, limit
    )


@router.get("/schedules/{rule_id}", response_model=ScheduleRuleRead)
async def get_schedule(
    rule_id: uuid.UUID, principal: StaffDep, session: DbSession
) -> ScheduleRuleRead:
    """Una regla; ajena al alcance del principal → `404`."""
    return await SchedulesService(session, principal).get(rule_id)


@router.post("/schedules", response_model=ScheduleRuleRead, status_code=201)
async def create_schedule(
    payload: ScheduleRuleCreate, admin: AdminDep, session: DbSession
) -> ScheduleRuleRead:
    """Alta de regla; solape con otra activa → `409 schedule_overlap`."""
    return await SchedulesService(session, admin).create(payload)


@router.patch("/schedules/{rule_id}", response_model=ScheduleRuleRead)
async def update_schedule(
    rule_id: uuid.UUID, payload: ScheduleRuleUpdate, admin: AdminDep, session: DbSession
) -> ScheduleRuleRead:
    """Edición parcial; `active=false` libera la franja."""
    return await SchedulesService(session, admin).update(rule_id, payload)


# --------------------------------------------------------------------- bloqueos


@router.get("/blocks", response_model=BlockPage)
async def list_blocks(
    principal: StaffDep,
    session: DbSession,
    desde: Annotated[datetime | None, Query(alias="from")] = None,
    hasta: Annotated[datetime | None, Query(alias="to")] = None,
    professional_id: Annotated[uuid.UUID | None, Query()] = None,
    chair_id: Annotated[uuid.UUID | None, Query()] = None,
    cursor: Cursor = None,
    limit: Limit = 50,
) -> BlockPage:
    """Bloqueos vigentes que intersectan `[from, to)` (el odontólogo, solo los propios)."""
    return await BlocksService(session, principal).list(
        desde, hasta, professional_id, chair_id, cursor, limit
    )


@router.get("/blocks/{block_id}", response_model=BlockRead)
async def get_block(block_id: uuid.UUID, principal: StaffDep, session: DbSession) -> BlockRead:
    """Un bloqueo vigente; ajeno al alcance del principal → `404`."""
    return await BlocksService(session, principal).get(block_id)


@router.post("/blocks", response_model=BlockRead, status_code=201)
async def create_block(payload: BlockCreate, principal: StaffDep, session: DbSession) -> BlockRead:
    """Alta de bloqueo (admin/recepción; odontólogo solo sobre su propia agenda)."""
    return await BlocksService(session, principal).create(payload)


@router.post("/blocks/closure", response_model=BlockList, status_code=201)
async def create_closure(payload: ClosureCreate, admin: AdminDep, session: DbSession) -> BlockList:
    """Feriado o cierre de clínica: un bloqueo por sillón activo (RN-BL-04)."""
    return await BlocksService(session, admin).create_closure(payload)


@router.patch("/blocks/{block_id}", response_model=BlockRead)
async def update_block(
    block_id: uuid.UUID, payload: BlockUpdate, admin: AdminDep, session: DbSession
) -> BlockRead:
    """Edición de un bloqueo futuro, o del fin de uno en curso (RN-BL-03)."""
    return await BlocksService(session, admin).update(block_id, payload)


@router.delete("/blocks/{block_id}", status_code=204)
async def remove_block(block_id: uuid.UUID, admin: AdminDep, session: DbSession) -> Response:
    """Retiro lógico de un bloqueo futuro."""
    await BlocksService(session, admin).remove(block_id)
    return Response(status_code=204)
