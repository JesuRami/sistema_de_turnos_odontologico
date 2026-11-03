"""Router del dominio clinic: perfil (C-06) y políticas operativas (C-04, US-004)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import require_roles
from app.common.principal import Principal
from app.core.deps import get_db
from app.models import UserRole
from app.modules.clinic.schemas import ClinicPolicies, ClinicPoliciesUpdate, ClinicProfile
from app.modules.clinic.service import PoliciesService, get_clinic_profile

router = APIRouter(prefix="/api/clinic", tags=["clinic"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
AdminDep = Annotated[Principal, Depends(require_roles(UserRole.ADMIN))]
ReaderDep = Annotated[Principal, Depends(require_roles(UserRole.ADMIN, UserRole.RECEPCION))]
StaffDep = Annotated[
    Principal,
    Depends(require_roles(UserRole.ADMIN, UserRole.RECEPCION, UserRole.ODONTOLOGO)),
]


@router.get("", response_model=ClinicProfile)
async def get_profile(principal: StaffDep, session: DbSession) -> ClinicProfile:
    """Nombre y zona horaria de la clínica del principal (la SPA dibuja en esa zona)."""
    return await get_clinic_profile(session, principal)


@router.get("/policies", response_model=ClinicPolicies)
async def get_policies(principal: ReaderDep, session: DbSession) -> ClinicPolicies:
    """Políticas vigentes de la clínica del principal (admin y recepción)."""
    return await PoliciesService(session, principal).get()


@router.patch("/policies", response_model=ClinicPolicies)
async def update_policies(
    payload: ClinicPoliciesUpdate, admin: AdminDep, session: DbSession
) -> ClinicPolicies:
    """Cambios parciales auditados; solo afectan lo que se programe después."""
    return await PoliciesService(session, admin).update(payload)
