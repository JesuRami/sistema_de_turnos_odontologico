"""Contrato de salud observable: GET /health y GET /ready (spec-driven)."""

import httpx
import pytest
from app.core.settings import Settings
from app.main import create_app
from redis.asyncio import Redis


@pytest.fixture()
def app() -> object:
    """App de test (Settings desde entorno dummy de conftest)."""
    return create_app()


async def test_health_responde_200_ok(app: object) -> None:
    """WHEN API sana y se pide GET /health THEN 200 {"status":"ok"} en <1s."""
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", timeout=1.0
    ) as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ready_sin_dependencias_responde_503() -> None:
    """WHEN Postgres/Redis caídos y se pide GET /ready THEN 503 que nombra la dependencia."""
    # Puerto 1 cerrado: dependencias caídas de forma explícita (no depende del entorno).
    caido = Settings(  # type: ignore[call-arg]
        DATABASE_URL="postgresql+asyncpg://turnos:x@127.0.0.1:1/turnos",
        REDIS_URL="redis://127.0.0.1:1/0",
    )
    transport = httpx.ASGITransport(app=create_app(caido))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", timeout=10.0
    ) as client:
        response = await client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert "detail" in body
    assert "postgres" in body["detail"] or "redis" in body["detail"]
    assert "Traceback" not in body["detail"]


@pytest.mark.integration
async def test_ready_con_dependencias_arriba_responde_200(app: object, redis_client: Redis) -> None:
    """WHEN Postgres/Redis alcanzables (DATABASE_URL con `+asyncpg`) THEN 200 ready."""
    _ = redis_client
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", timeout=10.0
    ) as client:
        response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
