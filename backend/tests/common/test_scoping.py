"""Alcance "odontólogo solo lo suyo" resuelto en SQL (C-03 tasks 5.3/5.4)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from app.common.exceptions import DomainError
from app.common.principal import Principal
from app.common.scoping import get_one_scoped_or_404, scope_by_professional
from app.models import Professional, ScheduleRule, UserRole
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import (
    make_chair,
    make_clinic,
    make_professional,
    make_schedule_rule,
    make_user,
)

pytestmark = pytest.mark.integration


def _principal(
    clinic_id: uuid.UUID,
    *roles: UserRole,
    professional_id: uuid.UUID | None = None,
) -> Principal:
    return Principal(
        user_id=uuid.uuid4(),
        clinic_id=clinic_id,
        email="staff.ficticio@example.com",
        roles=frozenset(roles),
        professional_id=professional_id,
        sid=str(uuid.uuid4()),
        must_change_password=False,
    )


async def _escenario(session: AsyncSession) -> dict[str, Any]:
    """Clínica A con dos odontólogos (2 filas c/u) y clínica B con una fila."""
    clinica_a = await make_clinic(session)
    clinica_b = await make_clinic(session)
    sillon_a = await make_chair(session, clinica_a)
    prof_a1 = await make_professional(session, clinica_a, display_name="Dra. Ficticia A1")
    prof_a2 = await make_professional(session, clinica_a, display_name="Dr. Ficticio A2")
    sillon_b = await make_chair(session, clinica_b)
    prof_b = await make_professional(session, clinica_b, display_name="Dr. Ficticio B")

    # Días distintos: el EXCLUDE de C-04 prohíbe reglas solapadas del mismo profesional+sillón.
    a1 = [
        await make_schedule_rule(session, clinica_a, prof_a1, sillon_a, weekday=dia)
        for dia in range(2)
    ]
    a2 = [
        await make_schedule_rule(session, clinica_a, prof_a2, sillon_a, weekday=dia)
        for dia in range(2)
    ]
    b = [await make_schedule_rule(session, clinica_b, prof_b, sillon_b)]
    return {
        "clinica_a": clinica_a,
        "clinica_b": clinica_b,
        "prof_a1": prof_a1,
        "prof_a2": prof_a2,
        "prof_b": prof_b,
        "a1": a1,
        "a2": a2,
        "b": b,
    }


async def _ids(session: AsyncSession, principal: Principal, table: Any) -> set[uuid.UUID]:
    col = table.id
    prof_col = table.professional_id
    stmt = scope_by_professional(select(col), principal, prof_col)
    return {fila[0] for fila in (await session.execute(stmt)).all()}


async def test_odontologo_ve_solo_sus_filas_en_schedule_rule(
    db_session: AsyncSession,
) -> None:
    """WHEN consulta un odontólogo THEN recibe solo sus filas, no las del colega."""
    datos = await _escenario(db_session)
    prof_a1 = datos["prof_a1"]
    principal = _principal(datos["clinica_a"].id, UserRole.ODONTOLOGO, professional_id=prof_a1.id)

    visibles = await _ids(db_session, principal, ScheduleRule)

    assert visibles == {fila.id for fila in datos["a1"]}


async def test_recepcion_y_admin_ven_toda_la_clinica(
    db_session: AsyncSession,
) -> None:
    """WHEN consulta recepción/admin THEN ve las filas de ambos profesionales de A."""
    datos = await _escenario(db_session)
    esperadas = {fila.id for fila in datos["a1"] + datos["a2"]}

    for rol in (UserRole.RECEPCION, UserRole.ADMIN):
        principal = _principal(datos["clinica_a"].id, rol)
        visibles = await _ids(db_session, principal, ScheduleRule)
        assert visibles == esperadas


async def test_una_clinica_b_nunca_aparece(db_session: AsyncSession) -> None:
    """WHEN se consulta desde A THEN ninguna fila de B (aunque el rol sea admin)."""
    datos = await _escenario(db_session)
    principal = _principal(datos["clinica_a"].id, UserRole.ADMIN)

    visibles = await _ids(db_session, principal, ScheduleRule)

    assert visibles.isdisjoint({fila.id for fila in datos["b"]})


async def test_odontologo_ve_solo_su_propio_professional(
    db_session: AsyncSession,
) -> None:
    """WHEN el recurso es `professional` THEN el odontólogo solo se ve a sí mismo."""
    datos = await _escenario(db_session)
    principal = _principal(
        datos["clinica_a"].id, UserRole.ODONTOLOGO, professional_id=datos["prof_a1"].id
    )

    stmt = scope_by_professional(select(Professional.id), principal, Professional.id)
    visibles = {fila[0] for fila in (await db_session.execute(stmt)).all()}

    assert visibles == {datos["prof_a1"].id}


async def test_la_sentencia_lleva_ambos_predicados_y_no_filtra_en_python(
    db_session: AsyncSession,
) -> None:
    """WHEN se arma la consulta THEN el SQL incluye clinic_id y professional_id."""
    _ = db_session
    principal = _principal(uuid.uuid4(), UserRole.ODONTOLOGO, professional_id=uuid.uuid4())

    stmt = scope_by_professional(select(ScheduleRule.id), principal, ScheduleRule.professional_id)
    sql = str(stmt)

    assert "schedule_rule.clinic_id" in sql
    assert "schedule_rule.professional_id" in sql
    assert "WHERE" in sql


async def test_odontologo_sin_profesional_da_403(db_session: AsyncSession) -> None:
    """WHEN falta `professional_id` THEN 403 y no se ejecuta un filtro nulo."""
    _ = db_session
    principal = _principal(uuid.uuid4(), UserRole.ODONTOLOGO)

    with pytest.raises(DomainError) as exc:
        scope_by_professional(select(ScheduleRule.id), principal, ScheduleRule.professional_id)

    assert exc.value.status_code == 403
    assert exc.value.detail == "forbidden_scope"


async def test_fila_de_otro_profesional_por_id_da_404(db_session: AsyncSession) -> None:
    """WHEN se pide por id una fila ajena THEN 404 (no 403) sin revelar existencia."""
    datos = await _escenario(db_session)
    principal = _principal(
        datos["clinica_a"].id,
        UserRole.ODONTOLOGO,
        professional_id=datos["prof_a1"].id,
    )
    ajena = datos["a2"][0]

    stmt = scope_by_professional(select(ScheduleRule.id), principal, ScheduleRule.professional_id)

    with pytest.raises(DomainError) as exc:
        await get_one_scoped_or_404(db_session, stmt, ScheduleRule.id, ajena.id)

    assert exc.value.status_code == 404
    assert exc.value.detail == "not_found"


async def test_fila_propia_por_id_devuelve_la_fila(db_session: AsyncSession) -> None:
    """WHEN se pide por id una fila propia THEN se devuelve."""
    datos = await _escenario(db_session)
    principal = _principal(
        datos["clinica_a"].id,
        UserRole.ODONTOLOGO,
        professional_id=datos["prof_a1"].id,
    )
    propia = datos["a1"][0]

    stmt = scope_by_professional(select(ScheduleRule.id), principal, ScheduleRule.professional_id)
    fila = await get_one_scoped_or_404(db_session, stmt, ScheduleRule.id, propia.id)

    assert fila[0] == propia.id


async def test_admin_puede_leer_por_id_una_fila_cualquiera_de_su_clinica(
    db_session: AsyncSession,
) -> None:
    """WHEN un admin pide por id una fila de la clínica THEN la obtiene."""
    datos = await _escenario(db_session)
    principal = _principal(datos["clinica_a"].id, UserRole.ADMIN)
    fila_ajena = datos["a2"][0]

    stmt = scope_by_professional(select(ScheduleRule.id), principal, ScheduleRule.professional_id)
    fila = await get_one_scoped_or_404(db_session, stmt, ScheduleRule.id, fila_ajena.id)

    assert fila[0] == fila_ajena.id


async def test_usuario_odontologo_real_se_crea_con_su_profesional(
    db_session: AsyncSession,
) -> None:
    """Sanidad del escenario: la fila de `user` exige profesional para odontólogo."""
    datos = await _escenario(db_session)
    user = await make_user(
        db_session,
        datos["clinica_a"],
        role=UserRole.ODONTOLOGO,
        professional_id=datos["prof_a1"].id,
    )

    assert user.professional_id == datos["prof_a1"].id
