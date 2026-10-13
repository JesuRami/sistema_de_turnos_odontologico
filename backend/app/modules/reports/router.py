"""Router del dominio reports (stub C-01; endpoints reales en C-13)."""

from fastapi import APIRouter

from app.modules.reports.schemas import ReportsStub
from app.modules.reports.service import ReportsService

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/ping", response_model=ReportsStub)
async def ping() -> ReportsStub:
    """Stub de cableado (routers finos → servicios)."""
    service = ReportsService()
    return ReportsStub(ping=await service.ping())
