"""Router del dominio agenda (stub C-01; endpoints reales en C-04/C-05)."""

from fastapi import APIRouter

from app.modules.agenda.schemas import AgendaStub
from app.modules.agenda.service import AgendaService

router = APIRouter(prefix="/agenda", tags=["agenda"])


@router.get("/ping", response_model=AgendaStub)
async def ping() -> AgendaStub:
    """Stub de cableado (routers finos → servicios)."""
    service = AgendaService()
    return AgendaStub(ping=await service.ping())
