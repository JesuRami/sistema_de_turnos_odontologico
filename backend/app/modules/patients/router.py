"""Router de pacientes para el personal (C-05, US-011 CA-1).

Solo admin y recepción (matriz RBAC de `03_actores_y_roles.md`): el odontólogo
no busca ni da de alta pacientes (`403 forbidden_role`).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import require_roles
from app.common.principal import Principal
from app.core.deps import get_db
from app.models import UserRole
from app.modules.patients.schemas import PatientCreate, PatientRead, PatientSearchResult
from app.modules.patients.service import PatientsService

router = APIRouter(prefix="/api", tags=["patients"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
FrontDeskDep = Annotated[Principal, Depends(require_roles(UserRole.ADMIN, UserRole.RECEPCION))]


@router.get("/patients", response_model=PatientSearchResult)
async def search_patients(
    q: Annotated[str, Query()], principal: FrontDeskDep, session: DbSession
) -> PatientSearchResult:
    """Teléfono → match por E.164; texto → similitud de nombre. Máximo 20."""
    return await PatientsService(session, principal).search(q)


@router.post("/patients", response_model=PatientRead, status_code=201)
async def create_patient(
    payload: PatientCreate, principal: FrontDeskDep, session: DbSession
) -> PatientRead:
    """Alta rápida; mismo teléfono y nombre → `409 patient_duplicate`."""
    return await PatientsService(session, principal).create(payload)
