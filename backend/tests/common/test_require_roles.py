"""RBAC: `require_roles`/`require_active_password` (C-03 task 5.2).

El principal se sustituye por `dependency_overrides` para probar la decisión de
autorización sin infraestructura; el caso "sin credencial" usa el camino real
(solo se reemplazan DB/Redis porque la falta de header corta antes de tocarlos).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

import httpx
import pytest
from app.common.dependencies import require_active_password, require_roles
from app.common.exceptions import register_exception_handlers
from app.common.principal import Principal
from app.core.deps import get_current_principal, get_db
from app.core.redis import get_redis
from app.models import UserRole
from fastapi import Depends, FastAPI

CLINIC_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")


def _principal(*roles: UserRole, must_change_password: bool = False) -> Principal:
    return Principal(
        user_id=uuid.uuid4(),
        clinic_id=CLINIC_ID,
        email="staff.ficticio@example.com",
        roles=frozenset(roles),
        professional_id=None,
        sid=str(uuid.uuid4()),
        must_change_password=must_change_password,
    )


def _app(principal: Principal | None) -> tuple[FastAPI, dict[str, bool]]:
    """App mínima con un endpoint protegido y una bandera de ejecución."""
    app = FastAPI()
    register_exception_handlers(app)
    ejecutado: dict[str, bool] = {}

    if principal is not None:
        app.dependency_overrides[get_current_principal] = lambda: principal

    @app.post("/_test/admin")
    async def _solo_admin(
        principal_: Annotated[Principal, Depends(require_roles(UserRole.ADMIN))],
    ) -> dict[str, str]:
        ejecutado["handler"] = True
        return {"user_id": str(principal_.user_id)}

    @app.post("/_test/password-gate")
    async def _password_gate(
        principal_: Annotated[Principal, Depends(require_active_password)],
    ) -> dict[str, str]:
        ejecutado["gate"] = True
        return {"user_id": str(principal_.user_id)}

    return app, ejecutado


async def _post(app: FastAPI, path: str, *, token: str | None = None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, headers=headers)


async def test_rol_permitido_ejecuta_el_handler() -> None:
    """WHEN el principal tiene el rol exigido THEN el handler corre y responde 200."""
    app, ejecutado = _app(_principal(UserRole.ADMIN))

    response = await _post(app, "/_test/admin", token="cualquiera")

    assert response.status_code == 200
    assert ejecutado == {"handler": True}


async def test_rol_no_permitido_da_403_sin_ejecutar_el_handler() -> None:
    """WHEN falta el rol THEN 403 forbidden_role y el handler no toca nada."""
    app, ejecutado = _app(_principal(UserRole.RECEPCION))

    response = await _post(app, "/_test/admin", token="cualquiera")

    assert response.status_code == 403
    assert response.json() == {"detail": "forbidden_role"}
    assert ejecutado == {}


async def test_roles_multiples_habilitan_el_endpoint() -> None:
    """WHEN el endpoint admite varios roles THEN cualquiera de ellos pasa."""
    app = FastAPI()
    register_exception_handlers(app)
    principal = _principal(UserRole.RECEPCION)
    app.dependency_overrides[get_current_principal] = lambda: principal

    @app.get("/_test/agenda")
    async def _agenda(
        _: Annotated[Principal, Depends(require_roles(UserRole.ADMIN, UserRole.RECEPCION))],
    ) -> dict[str, bool]:
        return {"ok": True}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/_test/agenda", headers={"Authorization": "Bearer x"})

    assert response.status_code == 200


async def test_sin_credencial_da_401_nunca_403() -> None:
    """WHEN no hay access token THEN 401 antes de llegar a la decisión de rol."""
    app, ejecutado = _app(None)

    async def _db() -> AsyncIterator[Any]:
        yield object()

    async def _redis() -> Any:
        return object()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_redis] = _redis

    response = await _post(app, "/_test/admin")

    assert response.status_code == 401
    assert ejecutado == {}


async def test_password_provisoria_bloquea_aunque_el_rol_sea_correcto() -> None:
    """WHEN must_change_password=true THEN 403 password_change_required."""
    app, ejecutado = _app(_principal(UserRole.ADMIN, must_change_password=True))

    response = await _post(app, "/_test/admin", token="cualquiera")

    assert response.status_code == 403
    assert response.json() == {"detail": "password_change_required"}
    assert ejecutado == {}


async def test_gate_suelto_tambien_bloquea_la_password_provisoria() -> None:
    """WHEN se usa `require_active_password` solo THEN el gate también aplica."""
    app, ejecutado = _app(_principal(UserRole.RECEPCION, must_change_password=True))

    response = await _post(app, "/_test/password-gate", token="cualquiera")

    assert response.status_code == 403
    assert response.json() == {"detail": "password_change_required"}
    assert ejecutado == {}


async def test_password_cambiada_deja_pasar_el_gate() -> None:
    """WHEN must_change_password=false THEN el gate deja ejecutar."""
    app, ejecutado = _app(_principal(UserRole.RECEPCION))

    response = await _post(app, "/_test/password-gate", token="cualquiera")

    assert response.status_code == 200
    assert ejecutado == {"gate": True}


@pytest.mark.parametrize("rol", ["desconocido", ""])
def test_rol_invalido_en_la_fabrica_falla_al_construir(rol: str) -> None:
    """WHEN se declara un rol inexistente THEN falla al armar la dependency."""
    with pytest.raises(ValueError):
        require_roles(rol)
