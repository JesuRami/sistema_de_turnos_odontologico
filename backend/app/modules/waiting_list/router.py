"""Router del dominio waiting_list (stub C-01; endpoints reales en C-12)."""

from fastapi import APIRouter

from app.modules.waiting_list.schemas import WaitingListStub
from app.modules.waiting_list.service import WaitingListService

router = APIRouter(prefix="/waiting-list", tags=["waiting_list"])


@router.get("/ping", response_model=WaitingListStub)
async def ping() -> WaitingListStub:
    """Stub de cableado (routers finos → servicios)."""
    service = WaitingListService()
    return WaitingListStub(ping=await service.ping())
