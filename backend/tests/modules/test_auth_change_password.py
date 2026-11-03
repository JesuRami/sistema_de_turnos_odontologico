"""Cambio de contraseña propia y gate de clave provisoria (C-03 tasks 6.7/7.x)."""

from __future__ import annotations

import httpx
import pytest
from app.core.security import hash_password
from app.core.settings import Settings
from app.models import Clinic, User, UserRole
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.auth_helpers import issue_session
from tests.factories import make_clinic, make_user, unique_email

pytestmark = pytest.mark.integration

VIEJA = "clave-vieja-ficticia-123"
NUEVA = "clave-nueva-ficticia-456"


async def _usuario(db_session: AsyncSession, **overrides: object) -> tuple[Clinic, User]:
    clinic = await make_clinic(db_session)
    valores: dict[str, object] = {
        "email": unique_email("staff.pwd"),
        "password_hash": hash_password(VIEJA),
        "must_change_password": False,
    }
    valores.update(overrides)
    user = await make_user(db_session, clinic, **valores)
    return clinic, user


async def _cambiar(
    app_client: httpx.AsyncClient, headers: dict[str, str], **body: object
) -> httpx.Response:
    payload = {"current_password": VIEJA, "new_password": NUEVA, **body}
    return await app_client.post("/api/auth/change-password", json=payload, headers=headers)


async def test_cambio_correcto_revoca_las_otras_sesiones(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN cambia la clave THEN la vieja no entra, la nueva sí y la otra sesión cae."""
    _clinic, user = await _usuario(db_session)
    actual = await issue_session(redis_client, settings, user)
    otra = await issue_session(redis_client, settings, user)

    response = await _cambiar(app_client, actual.headers)

    assert response.status_code == 200
    fila = (await db_session.execute(select(User).where(User.id == user.id))).scalar_one()
    assert fila.password_changed_at is not None
    assert fila.must_change_password is False
    # La sesión que hizo el cambio sigue viva; la otra fue revocada.
    assert (await app_client.get("/api/auth/me", headers=actual.headers)).status_code == 200
    assert (await app_client.get("/api/auth/me", headers=otra.headers)).status_code == 401

    vieja = await app_client.post("/api/auth/login", json={"email": user.email, "password": VIEJA})
    nueva = await app_client.post("/api/auth/login", json={"email": user.email, "password": NUEVA})
    assert vieja.status_code == 401
    assert nueva.status_code == 200


async def test_password_actual_incorrecta_no_cambia_nada(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN la actual es incorrecta THEN 401 y hash/sesiones intactos."""
    _clinic, user = await _usuario(db_session)
    actual = await issue_session(redis_client, settings, user)
    otra = await issue_session(redis_client, settings, user)
    hash_antes = user.password_hash

    response = await _cambiar(
        app_client, actual.headers, current_password="otra-clave-equivocada-999"
    )

    assert response.status_code == 401
    fila = (await db_session.execute(select(User).where(User.id == user.id))).scalar_one()
    assert fila.password_hash == hash_antes
    assert fila.password_changed_at is None
    assert (await app_client.get("/api/auth/me", headers=otra.headers)).status_code == 200


async def test_password_nueva_corta_da_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN la nueva tiene 11 caracteres THEN 422 y el hash no cambia."""
    _clinic, user = await _usuario(db_session)
    actual = await issue_session(redis_client, settings, user)
    hash_antes = user.password_hash

    response = await _cambiar(app_client, actual.headers, new_password="corta-12345")

    assert response.status_code == 422
    fila = (await db_session.execute(select(User).where(User.id == user.id))).scalar_one()
    assert fila.password_hash == hash_antes


async def test_password_igual_a_la_actual_da_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN la nueva es igual a la actual THEN 422 sin rehashear."""
    _clinic, user = await _usuario(db_session)
    actual = await issue_session(redis_client, settings, user)

    response = await _cambiar(app_client, actual.headers, new_password=VIEJA)

    assert response.status_code == 422


async def test_campo_extra_en_el_cambio_da_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN el body trae un campo extra THEN 422."""
    _clinic, user = await _usuario(db_session)
    actual = await issue_session(redis_client, settings, user)

    response = await _cambiar(app_client, actual.headers, campo_fantasma=1)

    assert response.status_code == 422


async def test_gate_de_password_provisoria(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN must_change_password=true THEN /users da 403 pero /me y el cambio no."""
    _clinic, user = await _usuario(db_session, must_change_password=True, role=UserRole.ADMIN)
    sesion = await issue_session(redis_client, settings, user)

    bloqueado = await app_client.get("/api/users", headers=sesion.headers)
    perfil = await app_client.get("/api/auth/me", headers=sesion.headers)
    cambio = await _cambiar(app_client, sesion.headers)

    assert bloqueado.status_code == 403
    assert bloqueado.json()["detail"] == "password_change_required"
    assert perfil.status_code == 200
    assert cambio.status_code == 200

    despues = await app_client.get("/api/users", headers=sesion.headers)
    assert despues.status_code == 200


async def test_logout_funciona_con_password_provisoria(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN must_change_password=true THEN el logout no queda bloqueado."""
    _clinic, user = await _usuario(db_session, must_change_password=True)
    sesion = await issue_session(redis_client, settings, user)

    response = await app_client.post("/api/auth/logout", headers=sesion.headers)

    assert response.status_code == 204
