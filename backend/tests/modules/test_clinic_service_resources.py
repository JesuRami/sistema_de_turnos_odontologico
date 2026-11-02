"""Servicios de recursos activos: excluyen inactivos y no cruzan clínicas."""

from app.modules.clinic.service import list_active_chairs, list_active_professionals
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_chair, make_clinic, make_professional


async def test_profesional_inactivo_excluido_pero_sigue_existiendo(
    db_session: AsyncSession,
) -> None:
    clinic = await make_clinic(db_session)
    activo = await make_professional(db_session, clinic, display_name="Dra. Ficticia Activa")
    inactivo = await make_professional(
        db_session, clinic, display_name="Dr. Ficticio Inactivo", active=False
    )

    resultado = await list_active_professionals(db_session, clinic.id)

    assert [p.id for p in resultado] == [activo.id]
    assert await db_session.get(type(inactivo), inactivo.id) is not None


async def test_sillon_inactivo_excluido(db_session: AsyncSession) -> None:
    clinic = await make_clinic(db_session)
    activo = await make_chair(db_session, clinic, name="Sillón Ficticio 1")
    await make_chair(db_session, clinic, name="Sillón Ficticio 2", active=False)

    resultado = await list_active_chairs(db_session, clinic.id)

    assert [c.id for c in resultado] == [activo.id]


async def test_listados_aislados_entre_clinicas(db_session: AsyncSession) -> None:
    clinic_a = await make_clinic(db_session)
    clinic_b = await make_clinic(db_session)
    prof_a = await make_professional(db_session, clinic_a)
    await make_professional(db_session, clinic_b)
    chair_a = await make_chair(db_session, clinic_a)
    await make_chair(db_session, clinic_b)

    profesionales = await list_active_professionals(db_session, clinic_a.id)
    sillones = await list_active_chairs(db_session, clinic_a.id)

    assert [p.id for p in profesionales] == [prof_a.id]
    assert {p.clinic_id for p in profesionales} == {clinic_a.id}
    assert [c.id for c in sillones] == [chair_a.id]
    assert {c.clinic_id for c in sillones} == {clinic_a.id}
