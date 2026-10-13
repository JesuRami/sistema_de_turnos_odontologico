"""Router del dominio booking_public (stub C-01; endpoints reales en C-07)."""

from fastapi import APIRouter

from app.modules.booking_public.schemas import BookingPublicStub
from app.modules.booking_public.service import BookingPublicService

router = APIRouter(prefix="/booking-public", tags=["booking_public"])


@router.get("/ping", response_model=BookingPublicStub)
async def ping() -> BookingPublicStub:
    """Stub de cableado (routers finos → servicios)."""
    service = BookingPublicService()
    return BookingPublicStub(ping=await service.ping())
