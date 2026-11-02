"""list_schedule_rules: aislado por clínica y filtrado por profesional."""

from datetime import time

from app.modules.clinic.service import list_schedule_rules
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_chair, make_clinic, make_professional, make_schedule_rule


async def test_reglas_solo_de_la_clinica_pedida(db_session: AsyncSession) -> None:
    clinic_a = await make_clinic(db_session)
    clinic_b = await make_clinic(db_session)
    prof_a = await make_professional(db_session, clinic_a)
    prof_b = await make_professional(db_session, clinic_b)
    rule_a = await make_schedule_rule(
        db_session, clinic_a, prof_a, await make_chair(db_session, clinic_a)
    )
    await make_schedule_rule(db_session, clinic_b, prof_b, await make_chair(db_session, clinic_b))

    reglas = await list_schedule_rules(db_session, clinic_a.id, prof_a.id)

    assert [r.id for r in reglas] == [rule_a.id]
    assert {r.clinic_id for r in reglas} == {clinic_a.id}


async def test_profesional_de_otra_clinica_no_devuelve_nada(db_session: AsyncSession) -> None:
    clinic_a = await make_clinic(db_session)
    clinic_b = await make_clinic(db_session)
    prof_b = await make_professional(db_session, clinic_b)
    await make_schedule_rule(db_session, clinic_b, prof_b, await make_chair(db_session, clinic_b))

    assert await list_schedule_rules(db_session, clinic_a.id, prof_b.id) == []


async def test_orden_por_dia_y_hora_y_filtra_por_profesional(db_session: AsyncSession) -> None:
    clinic = await make_clinic(db_session)
    chair = await make_chair(db_session, clinic)
    prof_1 = await make_professional(db_session, clinic)
    prof_2 = await make_professional(db_session, clinic, display_name="Dra. Ficticia Dos")
    martes = await make_schedule_rule(db_session, clinic, prof_1, chair, weekday=1)
    lunes_tarde = await make_schedule_rule(
        db_session, clinic, prof_1, chair, weekday=0, start_time=time(14), end_time=time(18)
    )
    lunes_manana = await make_schedule_rule(db_session, clinic, prof_1, chair, weekday=0)
    await make_schedule_rule(db_session, clinic, prof_2, chair, weekday=2)

    reglas = await list_schedule_rules(db_session, clinic.id, prof_1.id)

    assert [r.id for r in reglas] == [lunes_manana.id, lunes_tarde.id, martes.id]
