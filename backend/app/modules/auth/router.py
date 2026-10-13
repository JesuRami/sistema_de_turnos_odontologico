"""Router del dominio auth (stub C-01; endpoints reales en C-03)."""

from fastapi import APIRouter

from app.modules.auth.schemas import AuthStub
from app.modules.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/ping", response_model=AuthStub)
async def ping() -> AuthStub:
    """Stub de cableado (routers finos → servicios)."""
    service = AuthService()
    return AuthStub(ping=await service.ping())


@router.post("/echo", response_model=AuthStub)
async def echo(payload: AuthStub) -> AuthStub:
    """Borde con body para verificar validación estricta (`extra='forbid'`)."""
    return payload
