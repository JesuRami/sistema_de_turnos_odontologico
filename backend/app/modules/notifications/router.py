"""Router del dominio notifications (stub C-01; endpoints reales en C-10)."""

from fastapi import APIRouter

from app.modules.notifications.schemas import NotificationsStub
from app.modules.notifications.service import NotificationsService

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/ping", response_model=NotificationsStub)
async def ping() -> NotificationsStub:
    """Stub de cableado (routers finos → servicios)."""
    service = NotificationsService()
    return NotificationsStub(ping=await service.ping())
