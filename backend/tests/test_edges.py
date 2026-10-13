"""Bordes API: validación estricta Pydantic v2 + envolvente uniforme de errores."""

import httpx
import pytest
from app.main import create_app


@pytest.fixture()
def app() -> object:
    """App de test."""
    return create_app()


async def test_campo_extra_rechazado_con_422(app: object) -> None:
    """WHEN campo no declarado en endpoint con body THEN 422 {"detail":...} sin traza."""
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", timeout=5.0
    ) as client:
        response = await client.post("/auth/echo", json={"ping": "ok", "campo_fantasma": 1})
    assert response.status_code == 422
    body = response.json()
    assert "detail" in body
    assert "Traceback" not in str(body)


async def test_echo_valido_responde_200(app: object) -> None:
    """Borde válido pasa la validación estricta."""
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", timeout=5.0
    ) as client:
        response = await client.post("/auth/echo", json={"ping": "ok"})
    assert response.status_code == 200
    assert response.json() == {"ping": "ok"}


async def test_rate_limit_global_activo(app: object) -> None:
    """El rate-limit global responde 429 con envolvente {"detail":...} al excederse."""
    from app.core.settings import get_settings

    settings = get_settings()
    settings.BOOKING_RATE_LIMIT = "2/minute"
    limited = create_app(settings)
    transport = httpx.ASGITransport(app=limited)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", timeout=5.0
    ) as client:
        await client.post("/auth/echo", json={"ping": "ok"})
        await client.post("/auth/echo", json={"ping": "ok"})
        response = await client.post("/auth/echo", json={"ping": "ok"})
    assert response.status_code == 429
    assert "detail" in response.json()
