"""`GET /api/auth/me`: perfil propio sin datos sensibles (C-03 task 6.6)."""

from __future__ import annotations

import httpx
import pytest
from app.core.settings import Settings
from app.models import UserRole
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tests.auth_helpers import issue_session
from tests.factories import make_clinic, make_professional, make_user

pytestmark = pytest.mark.integration


async def test_me_devuelve_el_perfil_sin_hash_ni_tokens(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN consulta su perfil THEN vienen sus datos y ningún secreto."""
    clinic = await make_clinic(db_session)
    user = await make_user(db_session, clinic, must_change_password=False)
    sesion = await issue_session(redis_client, settings, user)

    response = await app_client.get("/api/auth/me", headers=sesion.headers)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(user.id)
    assert body["email"] == user.email
    assert body["role"] == user.role.value
    assert body["clinic_id"] == str(clinic.id)
    assert "password_hash" not in body
    assert "access_token" not in body
    assert sesion.access_token not in response.text


async def test_me_de_odontologo_incluye_su_profesional(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN es odontólogo THEN incluye el `professional_id` al que está atado."""
    clinic = await make_clinic(db_session)
    professional = await make_professional(db_session, clinic)
    user = await make_user(
        db_session,
        clinic,
        role=UserRole.ODONTOLOGO,
        professional_id=professional.id,
    )
    sesion = await issue_session(redis_client, settings, user)

    response = await app_client.get("/api/auth/me", headers=sesion.headers)

    assert response.status_code == 200
    assert response.json()["professional_id"] == str(professional.id)


async def test_me_sin_token_da_401(app_client: httpx.AsyncClient) -> None:
    """WHEN no hay token THEN 401 (nunca 403)."""
    response = await app_client.get("/api/auth/me")

    assert response.status_code == 401
