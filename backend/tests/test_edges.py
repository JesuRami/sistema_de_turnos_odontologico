"""Bordes API: validación estricta Pydantic v2 + envolvente uniforme de errores."""

import httpx
import pytest
from app.main import create_app


@pytest.fixture()
def app() -> object:
    """App de test (sin DB: los 422 de borde se resuelven en validación)."""
    return create_app()


async def test_campo_extra_rechazado_con_422(app: object) -> None:
    """WHEN campo no declarado en el login THEN 422 {"detail":...} sin traza."""
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", timeout=5.0
    ) as client:
        response = await client.post(
            "/api/auth/login",
            json={
                "email": "staff.ficticio@example.com",
                "password": "clave-ficticia-123",
                "campo_fantasma": 1,
            },
        )
    assert response.status_code == 422
    body = response.json()
    assert "detail" in body
    assert "Traceback" not in str(body)


async def test_login_sin_password_es_422(app: object) -> None:
    """WHEN falta un campo obligatorio del login THEN 422 de validación."""
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", timeout=5.0
    ) as client:
        response = await client.post(
            "/api/auth/login", json={"email": "staff.ficticio@example.com"}
        )
    assert response.status_code == 422


async def test_stubs_de_auth_eliminados(app: object) -> None:
    """WHEN se llama el viejo stub THEN ya no existe (404)."""
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", timeout=5.0
    ) as client:
        response = await client.post("/auth/echo", json={"ping": "ok"})
    assert response.status_code == 404


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
        await client.get("/openapi.json")
        await client.get("/openapi.json")
        response = await client.get("/openapi.json")
    assert response.status_code == 429
    assert "detail" in response.json()
