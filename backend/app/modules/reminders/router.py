"""Router del dominio reminders (stub C-01; endpoints reales en C-09)."""

from fastapi import APIRouter

from app.modules.reminders.schemas import RemindersStub
from app.modules.reminders.service import RemindersService

router = APIRouter(prefix="/reminders", tags=["reminders"])


@router.get("/ping", response_model=RemindersStub)
async def ping() -> RemindersStub:
    """Stub de cableado (routers finos → servicios)."""
    service = RemindersService()
    return RemindersStub(ping=await service.ping())
