"""Router del dominio users (stub C-01; endpoints reales en C-03)."""

from fastapi import APIRouter

from app.modules.users.schemas import UsersStub
from app.modules.users.service import UsersService

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/ping", response_model=UsersStub)
async def ping() -> UsersStub:
    """Stub de cableado (routers finos → servicios)."""
    service = UsersService()
    return UsersStub(ping=await service.ping())
