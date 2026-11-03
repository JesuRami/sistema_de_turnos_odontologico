"""Ciclo integral de autenticación + RBAC + alcance (C-03 task 9.1)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

import httpx
import pytest
from app.common.dependencies import require_roles
from app.common.principal import Principal
from app.common.scoping import get_one_scoped_or_404, scope_by_professional
from app.core.deps import get_db
from app.core.settings import Settings
from app.models import ScheduleRule, UserRole
from fastapi import Depends, FastAPI
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.auth_helpers import issue_session
from tests.factories import (
    make_chair,
    make_clinic,
    make_professional,
    make_schedule_rule,
    make_user,
)

pytestmark = pytest.mark.integration


def _rutas(app: FastAPI) -> None:
    """Endpoints internos de prueba (C-05 aún no existe)."""

    @app.post("/_test/turnos")
    async def _crear_turno(
        principal: Annotated[Principal, Depends(require_roles(UserRole.RECEPCION, UserRole.ADMIN))],
    ) -> dict[str, str]:
        return {"clinic_id": str(principal.clinic_id), "status": "creado"}

    @app.get("/_test/mis-filas")
    async def _mis_filas(
        principal: Annotated[
            Principal,
            Depends(require_roles(UserRole.ODONTOLOGO, UserRole.ADMIN, UserRole.RECEPCION)),
        ],
        session: Annotated[AsyncSession, Depends(get_db)],
    ) -> dict[str, list[str]]:
        stmt = scope_by_professional(
            select(ScheduleRule.id), principal, ScheduleRule.professional_id
        )
        filas = (await session.execute(stmt)).scalars().all()
        return {"ids": [str(fila) for fila in filas]}

    @app.get("/_test/fila/{fila_id}")
    async def _fila(
        fila_id: uuid.UUID,
        principal: Annotated[
            Principal,
            Depends(require_roles(UserRole.ODONTOLOGO, UserRole.ADMIN, UserRole.RECEPCION)),
        ],
        session: Annotated[AsyncSession, Depends(get_db)],
    ) -> dict[str, str]:
        stmt = scope_by_professional(
            select(ScheduleRule.id), principal, ScheduleRule.professional_id
        )
        fila = await get_one_scoped_or_404(session, stmt, ScheduleRule.id, fila_id)
        return {"id": str(fila[0])}


async def _escenario(
    app_instance: FastAPI, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> dict[str, Any]:
    _rutas(app_instance)
    clinica_a = await make_clinic(db_session)
    clinica_b = await make_clinic(db_session)
    sillon_a = await make_chair(db_session, clinica_a)
    sillon_b = await make_chair(db_session, clinica_b)
    prof_a1 = await make_professional(db_session, clinica_a, display_name="Dra. A1")
    prof_a2 = await make_professional(db_session, clinica_a, display_name="Dr. A2")
    prof_b = await make_professional(db_session, clinica_b, display_name="Dr. B")
    filas_a1 = [
        await make_schedule_rule(db_session, clinica_a, prof_a1, sillon_a) for _ in range(2)
    ]
    filas_a2 = [await make_schedule_rule(db_session, clinica_a, prof_a2, sillon_a)]
    filas_b = [await make_schedule_rule(db_session, clinica_b, prof_b, sillon_b)]

    admin = await make_user(db_session, clinica_a, role=UserRole.ADMIN, must_change_password=False)
    recepcion = await make_user(
        db_session, clinica_a, role=UserRole.RECEPCION, must_change_password=False
    )
    odontologo_a1 = await make_user(
        db_session,
        clinica_a,
        role=UserRole.ODONTOLOGO,
        professional_id=prof_a1.id,
        must_change_password=False,
    )
    return {
        "clinica_a": clinica_a,
        "clinica_b": clinica_b,
        "prof_a1": prof_a1,
        "filas_a1": filas_a1,
        "filas_a2": filas_a2,
        "filas_b": filas_b,
        "admin": admin,
        "recepcion": recepcion,
        "odontologo_a1": odontologo_a1,
        "sesion_admin": await issue_session(redis_client, settings, admin),
        "sesion_recepcion": await issue_session(redis_client, settings, recepcion),
        "sesion_odontologo": await issue_session(redis_client, settings, odontologo_a1),
    }


async def test_ciclo_completo_de_roles_y_aislamiento(
    app_instance: FastAPI,
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN se encadenan los actores THEN cada uno ve y puede solo lo suyo."""
    datos = await _escenario(app_instance, db_session, redis_client, settings)

    # Recepción crea turno y NO gestiona usuarios.
    turno = await app_client.post("/_test/turnos", headers=datos["sesion_recepcion"].headers)
    usuarios = await app_client.get("/api/users", headers=datos["sesion_recepcion"].headers)
    assert turno.status_code == 200
    assert usuarios.status_code == 403

    # Odontólogo A1 ve solo sus filas y pedir la de A2 da 404.
    propias = await app_client.get("/_test/mis-filas", headers=datos["sesion_odontologo"].headers)
    assert propias.status_code == 200
    assert set(propias.json()["ids"]) == {str(f.id) for f in datos["filas_a1"]}
    ajena = await app_client.get(
        f"/_test/fila/{datos['filas_a2'][0].id}",
        headers=datos["sesion_odontologo"].headers,
    )
    assert ajena.status_code == 404

    # Admin ve toda la clínica A, nunca B.
    todas = await app_client.get("/_test/mis-filas", headers=datos["sesion_admin"].headers)
    ids_admin = set(todas.json()["ids"])
    assert ids_admin == {str(f.id) for f in datos["filas_a1"] + datos["filas_a2"]}
    assert ids_admin.isdisjoint({str(f.id) for f in datos["filas_b"]})

    # Admin desactiva a A1: su siguiente request da 401.
    baja = await app_client.patch(
        f"/api/users/{datos['odontologo_a1'].id}",
        json={"active": False},
        headers=datos["sesion_admin"].headers,
    )
    assert baja.status_code == 200
    assert (
        await app_client.get("/api/auth/me", headers=datos["sesion_odontologo"].headers)
    ).status_code == 401


async def test_usuario_de_otra_clinica_nunca_aparece_en_el_listado(
    app_instance: FastAPI,
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """WHEN B tiene usuarios THEN el listado de A no los incluye."""
    datos = await _escenario(app_instance, db_session, redis_client, settings)
    user_b = await make_user(db_session, datos["clinica_b"])

    response = await app_client.get("/api/users", headers=datos["sesion_admin"].headers)

    ids = {item["id"] for item in response.json()["items"]}
    assert str(user_b.id) not in ids
    assert all(item["email"].endswith("@example.com") for item in response.json()["items"])
