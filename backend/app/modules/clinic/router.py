"""Router del dominio clinic (stub C-01; endpoints reales en C-02)."""

from fastapi import APIRouter

from app.modules.clinic.schemas import ClinicStub
from app.modules.clinic.service import ClinicService

router = APIRouter(prefix="/clinic", tags=["clinic"])


@router.get("/ping", response_model=ClinicStub)
async def ping() -> ClinicStub:
    """Stub de cableado (routers finos → servicios)."""
    service = ClinicService()
    return ClinicStub(ping=await service.ping())
