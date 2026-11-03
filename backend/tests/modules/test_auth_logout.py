"""Logout idempotente: revoca access y refresh, borra cookie (C-03 task 6.5)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from app.core.jwt import encode_access_token
from app.core.security import hash_password
from app.core.settings import Settings
from app.models import User, UserRole
from app.modules.auth.cookies import refresh_cookie_name
from app.modules.auth.sessions import session_alive
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tests.auth_helpers import sid_of
from tests.factories import make_clinic, make_user, unique_email

pytestmark = pytest.mark.integration

PASSWORD = "clave-ficticia-123"


async def _login(
    app_client: httpx.AsyncClient, db_session: AsyncSession, settings: Settings
) -> tuple[User, str, str]:
    clinic = await make_clinic(db_session)
    user = await make_user(
        db_session,
        clinic,
        email=unique_email("staff.logout"),
        password_hash=hash_password(PASSWORD),
        must_change_password=False,
    )
    response = await app_client.post(
        "/api/auth/login", json={"email": user.email, "password": PASSWORD}
    )
    access = response.json()["access_token"]
    refresh = response.cookies.get(refresh_cookie_name(settings)) or ""
    assert refresh
    return user, access, refresh


async def test_logout_revoca_access_y_refresh_y_borra_cookie(
    app_client: httpx.AsyncClient, db_session: AsyncSession, settings: Settings
) -> None:
    """WHEN se hace logout THEN 204, cookie borrada y tokens inservibles."""
    _user, access, refresh = await _login(app_client, db_session, settings)

    response = await app_client.post(
        "/api/auth/logout", headers={"Authorization": f"Bearer {access}"}
    )

    assert response.status_code == 204
    assert "max-age=0" in response.headers.get("set-cookie", "").lower()

    app_client.cookies.clear()
    app_client.cookies.set(refresh_cookie_name(settings), refresh)
    assert (await app_client.post("/api/auth/refresh")).status_code == 401
    assert (
        await app_client.get("/api/auth/me", headers={"Authorization": f"Bearer {access}"})
    ).status_code == 401


async def test_segundo_logout_es_204_sin_efectos(
    app_client: httpx.AsyncClient, db_session: AsyncSession, settings: Settings
) -> None:
    """WHEN se repite el logout THEN 204 idempotente."""
    _user, access, _refresh = await _login(app_client, db_session, settings)
    headers = {"Authorization": f"Bearer {access}"}

    primero = await app_client.post("/api/auth/logout", headers=headers)
    segundo = await app_client.post("/api/auth/logout", headers=headers)

    assert primero.status_code == 204
    assert segundo.status_code == 204


async def test_logout_sin_credenciales_es_204(app_client: httpx.AsyncClient) -> None:
    """WHEN no hay access ni cookie THEN 204 (no filtra si había sesión)."""
    response = await app_client.post("/api/auth/logout")

    assert response.status_code == 204


async def test_logout_con_access_vencido_pero_cookie_valida_revoca_la_familia(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    settings: Settings,
    redis_client: Redis,
) -> None:
    """WHEN el access venció pero la cookie sirve THEN la familia se revoca."""
    _user, _access, refresh = await _login(app_client, db_session, settings)
    sid = sid_of(refresh)
    vencido, _ = encode_access_token(
        user_id=uuid.uuid4(),
        clinic_id=uuid.uuid4(),
        roles=[UserRole.ADMIN],
        email="staff.ficticio@example.com",
        sid=sid,
        settings=settings,
        clock=lambda: datetime.now(UTC) - timedelta(hours=2),
    )
    app_client.cookies.clear()
    app_client.cookies.set(refresh_cookie_name(settings), refresh)

    response = await app_client.post(
        "/api/auth/logout", headers={"Authorization": f"Bearer {vencido}"}
    )

    assert response.status_code == 204
    assert await session_alive(redis_client, sid) is False
