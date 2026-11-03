"""Gestión de usuarios por admin: altas, listado, PATCH, último admin y reset."""

from __future__ import annotations

import uuid

import httpx
import pytest
from app.core.security import hash_password, verify_password
from app.core.settings import Settings
from app.models import AuthEvent, AuthEventType, Clinic, User, UserRole
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.auth_helpers import AuthSession, issue_session
from tests.factories import (
    make_clinic,
    make_professional,
    make_user,
    unique_email,
)

pytestmark = pytest.mark.integration

CLAVE = "clave-admin-ficticia-123"
CLAVE_NUEVA = "clave-reset-ficticia-456"


async def _escenario(
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    *,
    must_change_password: bool = False,
) -> tuple[Clinic, User, AuthSession]:
    clinic = await make_clinic(db_session)
    admin = await make_user(
        db_session,
        clinic,
        email=unique_email("admin.ficticio"),
        password_hash=hash_password(CLAVE),
        role=UserRole.ADMIN,
        must_change_password=must_change_password,
    )
    sesion = await issue_session(redis_client, settings, admin)
    return clinic, admin, sesion


def _payload(**overrides: object) -> dict[str, object]:
    valores: dict[str, object] = {
        "email": unique_email("nuevo.staff"),
        "password": "clave-provisoria-123",
        "role": "recepcion",
    }
    valores.update(overrides)
    return valores


async def test_alta_de_recepcion_sin_profesional(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN admin crea recepción THEN 201, email minúsculas y clave provisoria."""
    clinic, _admin_user, sesion = await _escenario(db_session, redis_client, settings)
    email = unique_email("Recepcion.Mayusculas").upper()

    response = await app_client.post(
        "/api/users",
        json=_payload(email=email, role="recepcion"),
        headers=sesion.headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == email.lower()
    assert body["role"] == "recepcion"
    assert body["must_change_password"] is True
    assert "password" not in body
    assert "password_hash" not in body
    assert body["professional_id"] is None

    evento = (
        await db_session.execute(
            select(AuthEvent).where(
                AuthEvent.event == AuthEventType.USER_CREATED,
                AuthEvent.user_id == uuid.UUID(body["id"]),
            )
        )
    ).scalar_one()
    assert evento.actor_user_id is not None
    assert evento.clinic_id == clinic.id


async def test_odontologo_sin_profesional_da_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN falta `professional_id` para odontólogo THEN 422 y no se crea."""
    _clinic, _admin_user, sesion = await _escenario(db_session, redis_client, settings)

    response = await app_client.post(
        "/api/users",
        json=_payload(role="odontologo"),
        headers=sesion.headers,
    )

    assert response.status_code == 422


async def test_profesional_de_otra_clinica_da_422_sin_filtrar_datos(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN el profesional es de B THEN 422 sin revelar datos de B."""
    _clinic, _admin_user, sesion = await _escenario(db_session, redis_client, settings)
    clinica_b = await make_clinic(db_session)
    profesional_b = await make_professional(db_session, clinica_b, display_name="Dr. Secreto B")

    response = await app_client.post(
        "/api/users",
        json=_payload(role="odontologo", professional_id=str(profesional_b.id)),
        headers=sesion.headers,
    )

    assert response.status_code == 422
    assert "Secreto B" not in response.text
    assert str(clinica_b.id) not in response.text


async def test_email_duplicado_en_la_clinica_da_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN el email ya existe en la clínica THEN 422 sin PII."""
    clinic, _admin_user, sesion = await _escenario(db_session, redis_client, settings)
    existente = await make_user(db_session, clinic, email=unique_email("duplicado"))

    response = await app_client.post(
        "/api/users",
        json=_payload(email=existente.email),
        headers=sesion.headers,
    )

    assert response.status_code == 422
    assert existente.email not in response.text


async def test_body_con_clinic_id_da_422_y_no_crea_en_ninguna_clinica(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN el body impone `clinic_id` THEN 422 (tenant solo del principal)."""
    _clinic, _admin_user, sesion = await _escenario(db_session, redis_client, settings)
    otra = await make_clinic(db_session)

    response = await app_client.post(
        "/api/users",
        json=_payload(clinic_id=str(otra.id)),
        headers=sesion.headers,
    )

    assert response.status_code == 422


async def test_recepcion_no_puede_crear_usuarios(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN un principal recepción llama el alta THEN 403 forbidden_role."""
    clinic = await make_clinic(db_session)
    recepcion = await make_user(
        db_session,
        clinic,
        role=UserRole.RECEPCION,
        must_change_password=False,
    )
    sesion = await issue_session(redis_client, settings, recepcion)

    response = await app_client.post("/api/users", json=_payload(), headers=sesion.headers)

    assert response.status_code == 403
    assert response.json()["detail"] == "forbidden_role"


async def test_listado_por_cursor_solo_de_la_clinica_y_sin_hash(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN lista con limit=2 THEN pagina por cursor y no expone el hash."""
    _clinic, _admin_user, sesion = await _escenario(db_session, redis_client, settings)
    for _ in range(3):
        await app_client.post("/api/users", json=_payload(), headers=sesion.headers)

    primera = await app_client.get("/api/users", params={"limit": 2}, headers=sesion.headers)

    assert primera.status_code == 200
    body = primera.json()
    assert len(body["items"]) == 2
    assert body["next_cursor"]
    assert all("password_hash" not in item for item in body["items"])

    segunda = await app_client.get(
        "/api/users",
        params={"limit": 2, "cursor": body["next_cursor"]},
        headers=sesion.headers,
    )
    assert segunda.status_code == 200
    ids_primera = {item["id"] for item in body["items"]}
    ids_segunda = {item["id"] for item in segunda.json()["items"]}
    assert ids_primera.isdisjoint(ids_segunda)


async def test_listado_cross_tenant_mismo_email_en_a_y_b(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN A y B tienen el mismo email THEN A solo ve su usuario."""
    _clinic_a, _admin_user, sesion = await _escenario(db_session, redis_client, settings)
    email = unique_email("compartido")
    creado_a = await app_client.post(
        "/api/users", json=_payload(email=email), headers=sesion.headers
    )
    clinica_b = await make_clinic(db_session)
    user_b = await make_user(db_session, clinica_b, email=email)

    response = await app_client.get("/api/users", headers=sesion.headers)

    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["items"]}
    assert creado_a.json()["id"] in ids
    assert str(user_b.id) not in ids


@pytest.mark.parametrize("rol", [UserRole.RECEPCION, UserRole.ODONTOLOGO])
async def test_listado_prohibido_para_no_admin(
    rol: UserRole,
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN recepción u odontólogo listan THEN 403."""
    clinic = await make_clinic(db_session)
    professional = (
        await make_professional(db_session, clinic) if rol is UserRole.ODONTOLOGO else None
    )
    user = await make_user(
        db_session,
        clinic,
        role=rol,
        professional_id=professional.id if professional else None,
        must_change_password=False,
    )
    sesion = await issue_session(redis_client, settings, user)

    response = await app_client.get("/api/users", headers=sesion.headers)

    assert response.status_code == 403


async def test_patch_baja_logica_revoca_sesiones(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN admin desactiva THEN active=false, la fila vive y la sesión cae."""
    clinic, _admin_user, sesion = await _escenario(db_session, redis_client, settings)
    objetivo = await make_user(
        db_session, clinic, role=UserRole.RECEPCION, must_change_password=False
    )
    sesion_objetivo = await issue_session(redis_client, settings, objetivo)

    response = await app_client.patch(
        f"/api/users/{objetivo.id}",
        json={"active": False},
        headers=sesion.headers,
    )

    assert response.status_code == 200
    assert response.json()["active"] is False
    fila = (await db_session.execute(select(User).where(User.id == objetivo.id))).scalar_one()
    assert fila.active is False
    assert (
        await app_client.get("/api/auth/me", headers=sesion_objetivo.headers)
    ).status_code == 401
    evento = (
        await db_session.execute(
            select(AuthEvent).where(
                AuthEvent.event == AuthEventType.USER_DEACTIVATED,
                AuthEvent.user_id == objetivo.id,
            )
        )
    ).scalar_one()
    assert evento.actor_user_id is not None


async def test_delete_no_existe(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN se llama DELETE THEN 405 y el usuario sigue en la base."""
    clinic, _admin_user, sesion = await _escenario(db_session, redis_client, settings)
    objetivo = await make_user(db_session, clinic)

    response = await app_client.delete(f"/api/users/{objetivo.id}", headers=sesion.headers)

    assert response.status_code == 405
    assert (
        await db_session.execute(select(User).where(User.id == objetivo.id))
    ).scalar_one_or_none() is not None


async def test_cambio_de_rol_invalido_no_aplica(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN se promueve a odontólogo sin profesional THEN 422 y conserva el rol."""
    clinic, _admin_user, sesion = await _escenario(db_session, redis_client, settings)
    objetivo = await make_user(db_session, clinic, role=UserRole.RECEPCION)

    response = await app_client.patch(
        f"/api/users/{objetivo.id}",
        json={"role": "odontologo"},
        headers=sesion.headers,
    )

    assert response.status_code == 422
    await db_session.refresh(objetivo)
    assert objetivo.role is UserRole.RECEPCION


async def test_cambio_de_rol_revoca_sesiones_y_audita(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN cambia el rol THEN la sesión anterior cae y queda `role_changed`."""
    clinic, _admin_user, sesion = await _escenario(db_session, redis_client, settings)
    professional = await make_professional(db_session, clinic)
    objetivo = await make_user(
        db_session, clinic, role=UserRole.RECEPCION, must_change_password=False
    )
    sesion_objetivo = await issue_session(redis_client, settings, objetivo)

    response = await app_client.patch(
        f"/api/users/{objetivo.id}",
        json={"role": "odontologo", "professional_id": str(professional.id)},
        headers=sesion.headers,
    )

    assert response.status_code == 200
    assert response.json()["role"] == "odontologo"
    assert (
        await app_client.get("/api/auth/me", headers=sesion_objetivo.headers)
    ).status_code == 401
    evento = (
        await db_session.execute(
            select(AuthEvent).where(
                AuthEvent.event == AuthEventType.ROLE_CHANGED,
                AuthEvent.user_id == objetivo.id,
            )
        )
    ).scalar_one()
    assert isinstance(evento.payload, dict)
    assert evento.payload["to_role"] == "odontologo"


async def test_patch_de_otra_clinica_da_404(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN el id pertenece a B THEN 404 sin revelar existencia."""
    _clinic, _admin_user, sesion = await _escenario(db_session, redis_client, settings)
    clinica_b = await make_clinic(db_session)
    user_b = await make_user(db_session, clinica_b)

    response = await app_client.patch(
        f"/api/users/{user_b.id}",
        json={"active": False},
        headers=sesion.headers,
    )

    assert response.status_code == 404


async def test_ultimo_admin_no_puede_desactivarse(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN el único admin se desactiva THEN 409 y sigue activo."""
    _clinic, admin, sesion = await _escenario(db_session, redis_client, settings)

    response = await app_client.patch(
        f"/api/users/{admin.id}",
        json={"active": False},
        headers=sesion.headers,
    )

    assert response.status_code == 409
    await db_session.refresh(admin)
    assert admin.active is True


async def test_ultimo_admin_no_puede_quitarse_el_rol(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN el único admin cambia su rol THEN 409 y conserva admin."""
    _clinic, admin, sesion = await _escenario(db_session, redis_client, settings)

    response = await app_client.patch(
        f"/api/users/{admin.id}",
        json={"role": "recepcion"},
        headers=sesion.headers,
    )

    assert response.status_code == 409
    await db_session.refresh(admin)
    assert admin.role is UserRole.ADMIN


async def test_con_dos_admins_la_baja_procede(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN hay dos admins activos THEN desactivar a uno procede."""
    clinic, _admin, sesion = await _escenario(db_session, redis_client, settings)
    segundo = await make_user(db_session, clinic, role=UserRole.ADMIN, must_change_password=False)

    response = await app_client.patch(
        f"/api/users/{segundo.id}",
        json={"active": False},
        headers=sesion.headers,
    )

    assert response.status_code == 200
    assert response.json()["active"] is False


async def test_password_reset_provisorio_revoca_sesiones(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN admin resetea THEN 204, vieja inválida, nueva válida y flag=true."""
    clinic, _admin_user, sesion = await _escenario(db_session, redis_client, settings)
    objetivo = await make_user(
        db_session,
        clinic,
        role=UserRole.RECEPCION,
        password_hash=hash_password(CLAVE),
        must_change_password=False,
    )
    sesion_objetivo = await issue_session(redis_client, settings, objetivo)

    response = await app_client.post(
        f"/api/users/{objetivo.id}/password-reset",
        json={"new_password": CLAVE_NUEVA},
        headers=sesion.headers,
    )

    assert response.status_code == 204
    assert response.text == ""
    await db_session.refresh(objetivo)
    assert objetivo.must_change_password is True
    assert verify_password(CLAVE_NUEVA, objetivo.password_hash)
    assert not verify_password(CLAVE, objetivo.password_hash)
    assert (
        await app_client.get("/api/auth/me", headers=sesion_objetivo.headers)
    ).status_code == 401

    vieja = await app_client.post(
        "/api/auth/login", json={"email": objetivo.email, "password": CLAVE}
    )
    nueva = await app_client.post(
        "/api/auth/login", json={"email": objetivo.email, "password": CLAVE_NUEVA}
    )
    assert vieja.status_code == 401
    assert nueva.status_code == 200


async def test_password_reset_de_otra_clinica_da_404(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN el id del reset es de B THEN 404."""
    _clinic, _admin_user, sesion = await _escenario(db_session, redis_client, settings)
    clinica_b = await make_clinic(db_session)
    user_b = await make_user(db_session, clinica_b)

    response = await app_client.post(
        f"/api/users/{user_b.id}/password-reset",
        json={"new_password": CLAVE_NUEVA},
        headers=sesion.headers,
    )

    assert response.status_code == 404
