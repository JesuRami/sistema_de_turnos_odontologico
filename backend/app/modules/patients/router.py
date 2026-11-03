"""Router de pacientes para el personal (C-05, US-011 CA-1; detalle y fusión C-06).

Solo admin y recepción (matriz RBAC de `03_actores_y_roles.md`): el odontólogo
no busca ni da de alta pacientes (`403 forbidden_role`).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.clock import get_now
from app.common.dependencies import require_roles
from app.common.principal import Principal
from app.core.deps import get_db
from app.models import UserRole
from app.modules.patients.merge import merge_patients
from app.modules.patients.schemas import (
    PatientCreate,
    PatientDetail,
    PatientMergeRequest,
    PatientMergeResult,
    PatientRead,
    PatientSearchResult,
)
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


@router.get("/patients/{patient_id}", response_model=PatientDetail)
async def get_patient(
    patient_id: uuid.UUID, principal: FrontDeskDep, session: DbSession
) -> PatientDetail:
    """Ficha de un paciente de la clínica (incluye archivados); ajeno → `404`."""
    return await PatientsService(session, principal).get(patient_id)


@router.post("/patients/{patient_id}/merge", response_model=PatientMergeResult)
async def merge_patient(
    patient_id: uuid.UUID,
    payload: PatientMergeRequest,
    principal: FrontDeskDep,
    session: DbSession,
    now: Annotated[datetime, Depends(get_now)],
) -> PatientMergeResult:
    """Fusiona este paciente (duplicado) en `into_patient_id`; irreversible y auditado."""
    return await merge_patients(session, principal, patient_id, payload, now)
