"""Refresh rotativo: cookie, reuso, familia revocada y allowlist de Origin."""

from __future__ import annotations

import httpx
import pytest
from app.core.security import hash_password
from app.core.settings import Settings
from app.models import AuthEvent, AuthEventType, User
from app.modules.auth.cookies import refresh_cookie_name
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.auth_helpers import sid_of
from tests.factories import make_clinic, make_user, unique_email

pytestmark = pytest.mark.integration

PASSWORD = "clave-ficticia-123"


async def _usuario(db_session: AsyncSession) -> User:
    clinic = await make_clinic(db_session)
    return await make_user(
        db_session,
        clinic,
        email=unique_email("staff.refresh"),
        password_hash=hash_password(PASSWORD),
        must_change_password=False,
    )


async def _login(app_client: httpx.AsyncClient, user: User) -> httpx.Response:
    return await app_client.post(
        "/api/auth/login", json={"email": user.email, "password": PASSWORD}
    )


def _cookie_de(response: httpx.Response, settings: Settings) -> str:
    nombre = refresh_cookie_name(settings)
    valor = response.cookies.get(nombre)
    assert valor
    return valor


async def test_refresh_valido_rota_cookie_y_devuelve_access_nuevo(
    app_client: httpx.AsyncClient, db_session: AsyncSession, settings: Settings
) -> None:
    """WHEN se refresca THEN 200 con access nuevo y cookie distinta."""
    user = await _usuario(db_session)
    login = await _login(app_client, user)
    r0 = _cookie_de(login, settings)

    respuesta = await app_client.post("/api/auth/refresh")

    assert respuesta.status_code == 200
    body = respuesta.json()
    assert body["access_token"]
    assert 0 < body["expires_in"] <= 900
    r1 = _cookie_de(respuesta, settings)
    assert r1 != r0


async def test_refresh_anterior_ya_no_sirve(
    app_client: httpx.AsyncClient, db_session: AsyncSession, settings: Settings
) -> None:
    """WHEN se reusa el refresh rotado THEN 401 refresh_reuse y familia revocada."""
    user = await _usuario(db_session)
    login = await _login(app_client, user)
    r0 = _cookie_de(login, settings)
    rotado = await app_client.post("/api/auth/refresh")
    r1 = _cookie_de(rotado, settings)

    app_client.cookies.clear()
    app_client.cookies.set(refresh_cookie_name(settings), r0)
    reuso = await app_client.post("/api/auth/refresh")

    assert reuso.status_code == 401
    assert reuso.json()["detail"] == "refresh_reuse"

    # El refresh vigente tampoco sirve: la familia completa quedó revocada.
    app_client.cookies.clear()
    app_client.cookies.set(refresh_cookie_name(settings), r1)
    vigente = await app_client.post("/api/auth/refresh")
    assert vigente.status_code == 401

    eventos = (
        (
            await db_session.execute(
                select(AuthEvent).where(AuthEvent.event == AuthEventType.REFRESH_REUSE_DETECTED)
            )
        )
        .scalars()
        .all()
    )
    assert eventos


async def test_reuso_queda_auditado_sin_tokens(
    app_client: httpx.AsyncClient, db_session: AsyncSession, settings: Settings
) -> None:
    """WHEN hay reuso THEN el evento no contiene el refresh ni el access."""
    user = await _usuario(db_session)
    login = await _login(app_client, user)
    r0 = _cookie_de(login, settings)
    access = login.json()["access_token"]
    await app_client.post("/api/auth/refresh")

    app_client.cookies.clear()
    app_client.cookies.set(refresh_cookie_name(settings), r0)
    await app_client.post("/api/auth/refresh")

    evento = (
        await db_session.execute(
            select(AuthEvent).where(AuthEvent.event == AuthEventType.REFRESH_REUSE_DETECTED)
        )
    ).scalar_one()
    texto = str(evento.payload) + str(evento.user_id) + str(evento.subject_hash)
    assert r0 not in texto
    assert access not in texto


async def test_refresh_sin_cookie_da_401_y_borra_cookie(
    app_client: httpx.AsyncClient,
) -> None:
    """WHEN no hay cookie THEN 401 y `Set-Cookie` de borrado."""
    response = await app_client.post("/api/auth/refresh")

    assert response.status_code == 401
    set_cookie = response.headers.get("set-cookie", "")
    assert "max-age=0" in set_cookie.lower()


async def test_refresh_de_familia_revocada_da_401_y_borra_cookie(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    settings: Settings,
    redis_client: Redis,
) -> None:
    """WHEN la familia fue revocada THEN 401 genérico y cookie de borrado."""
    user = await _usuario(db_session)
    login = await _login(app_client, user)
    refresh = _cookie_de(login, settings)
    sid = sid_of(refresh)
    await redis_client.delete(f"auth:sess:{sid}", f"auth:rt:{sid}")

    response = await app_client.post("/api/auth/refresh")

    assert response.status_code == 401
    assert "max-age=0" in response.headers.get("set-cookie", "").lower()


async def test_origin_no_permitido_da_403(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """WHEN `Origin` no está en la allowlist THEN 403 sin tocar la sesión."""
    user = await _usuario(db_session)
    await _login(app_client, user)

    response = await app_client.post(
        "/api/auth/refresh", headers={"Origin": "http://malicioso.example.com"}
    )

    assert response.status_code == 403


async def test_origin_permitido_pasa(
    app_client: httpx.AsyncClient, db_session: AsyncSession, settings: Settings
) -> None:
    """WHEN `Origin` es el de CORS THEN el refresh procede."""
    user = await _usuario(db_session)
    await _login(app_client, user)
    permitido = settings.CORS_ORIGINS.split(",")[0].strip()

    response = await app_client.post("/api/auth/refresh", headers={"Origin": permitido})

    assert response.status_code == 200


async def test_un_refresh_no_sirve_como_access(
    app_client: httpx.AsyncClient, db_session: AsyncSession, settings: Settings
) -> None:
    """WHEN se usa la cookie/refresh como Bearer THEN 401 (type != access)."""
    user = await _usuario(db_session)
    login = await _login(app_client, user)
    refresh = _cookie_de(login, settings)

    response = await app_client.get("/api/auth/me", headers={"Authorization": f"Bearer {refresh}"})

    assert response.status_code == 401
