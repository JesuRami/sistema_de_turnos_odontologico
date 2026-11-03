"""Principal construido desde la DB (nunca desde los claims del access token)."""

from typing import Annotated, cast

import httpx
import pytest
from app.common.principal import Principal
from app.core.deps import get_current_principal
from app.core.jwt import encode_access_token
from app.core.settings import Settings
from app.models import UserRole
from app.modules.auth.sessions import create_session, revoke
from fastapi import Depends, FastAPI
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tests.auth_helpers import issue_session
from tests.factories import make_clinic, make_user

pytestmark = pytest.mark.integration


def _principal_route(app: FastAPI) -> None:
    @app.get("/_test/principal")
    async def _principal(
        principal: Annotated[Principal, Depends(get_current_principal)],
    ) -> dict[str, object]:
        return {
            "user_id": str(principal.user_id),
            "clinic_id": str(principal.clinic_id),
            "email": principal.email,
            "roles": sorted(rol.value for rol in principal.roles),
            "professional_id": (
                str(principal.professional_id) if principal.professional_id else None
            ),
            "must_change_password": principal.must_change_password,
        }


async def test_principal_toma_rol_y_tenant_de_la_fila_no_del_token(
    app_instance: FastAPI,
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN el token trae un rol elevado THEN el principal usa el rol real de la DB."""
    clinic = await make_clinic(db_session)
    user = await make_user(db_session, clinic, role=UserRole.RECEPCION)
    # Token firmado con roles=["admin"] pero el usuario es recepción: manda la DB.
    sesion = await issue_session(redis_client, settings, user, roles=[UserRole.ADMIN])
    _principal_route(app_instance)
    cliente = app_client

    response = await cliente.get("/_test/principal", headers=sesion.headers)

    assert response.status_code == 200
    body = response.json()
    assert body["roles"] == ["recepcion"]
    assert body["clinic_id"] == str(clinic.id)


async def test_usuario_inactivo_da_401(
    app_instance: FastAPI,
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN el usuario está inactivo THEN su access vigente deja de servir."""
    clinic = await make_clinic(db_session)
    user = await make_user(db_session, clinic, active=False)
    sesion = await issue_session(redis_client, settings, user)
    _principal_route(app_instance)

    response = await app_client.get("/_test/principal", headers=sesion.headers)

    assert response.status_code == 401


async def test_usuario_inexistente_en_la_base_da_401(
    app_instance: FastAPI,
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN el `sub` ya no existe en la clínica THEN 401 sin crear principal."""
    clinic = await make_clinic(db_session)
    user = await make_user(db_session, clinic)
    tokens = await create_session(
        redis_client,
        user_id=user.id,
        clinic_id=clinic.id,
        ttl_s=settings.JWT_REFRESH_DAYS * 86400,
    )
    access, _ = encode_access_token(
        user_id=user.id,
        clinic_id=clinic.id,
        roles=[UserRole.ADMIN],
        email=user.email,
        sid=tokens.sid,
        settings=settings,
    )
    await db_session.delete(user)
    await db_session.flush()
    _principal_route(app_instance)

    response = await app_client.get(
        "/_test/principal", headers={"Authorization": f"Bearer {access}"}
    )

    assert response.status_code == 401


async def test_sesion_revocada_invalida_el_access(
    app_instance: FastAPI,
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN la familia fue revocada THEN el access vigente responde 401."""
    clinic = await make_clinic(db_session)
    user = await make_user(db_session, clinic)
    sesion = await issue_session(redis_client, settings, user)
    await revoke(redis_client, sesion.sid, user.id)
    _principal_route(app_instance)

    response = await app_client.get("/_test/principal", headers=sesion.headers)

    assert response.status_code == 401


async def test_token_vencido_da_401_con_codigo(
    app_instance: FastAPI,
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN el token está vencido THEN 401 token_expired."""
    from datetime import UTC, datetime, timedelta

    clinic = await make_clinic(db_session)
    user = await make_user(db_session, clinic)
    tokens = await create_session(
        redis_client,
        user_id=user.id,
        clinic_id=clinic.id,
        ttl_s=settings.JWT_REFRESH_DAYS * 86400,
    )
    access, _ = encode_access_token(
        user_id=user.id,
        clinic_id=clinic.id,
        roles=[UserRole.ADMIN],
        email=user.email,
        sid=tokens.sid,
        settings=settings,
        clock=lambda: datetime.now(UTC) - timedelta(hours=1),
    )
    _principal_route(app_instance)

    response = await app_client.get(
        "/_test/principal", headers={"Authorization": f"Bearer {access}"}
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "token_expired"


async def test_sin_credenciales_da_401(
    app_instance: FastAPI, app_client: httpx.AsyncClient
) -> None:
    """WHEN no hay token THEN 401 (nunca 403)."""
    _principal_route(app_instance)

    response = await app_client.get("/_test/principal")

    assert response.status_code == 401


async def test_redis_caido_da_503_fail_closed(
    app_instance: FastAPI,
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN Redis no responde THEN 503 auth_unavailable (nunca 401 ni fail-open)."""
    from app.core.redis import get_redis
    from redis.asyncio import Redis as RedisClient

    clinic = await make_clinic(db_session)
    user = await make_user(db_session, clinic)
    sesion = await issue_session(redis_client, settings, user)
    caido = cast(
        RedisClient,
        RedisClient.from_url("redis://127.0.0.1:6399/15", decode_responses=True),
    )

    async def _caido() -> RedisClient:
        return caido

    app_instance.dependency_overrides[get_redis] = _caido
    _principal_route(app_instance)
    try:
        response = await app_client.get("/_test/principal", headers=sesion.headers)
    finally:
        await caido.aclose()

    assert response.status_code == 503
    assert response.json()["detail"] == "auth_unavailable"
