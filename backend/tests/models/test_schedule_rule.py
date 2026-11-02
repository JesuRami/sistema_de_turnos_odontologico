"""ScheduleRule: franja válida, vigencia y FKs compuestas intra-tenant."""

from datetime import date, time
from typing import Any

import pytest
from app.models import Chair, Clinic, Professional, ScheduleRule
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_chair, make_clinic, make_professional, make_schedule_rule


async def _recursos(session: AsyncSession) -> tuple[Clinic, Professional, Chair]:
    clinic = await make_clinic(session)
    professional = await make_professional(session, clinic)
    chair = await make_chair(session, clinic)
    return clinic, professional, chair


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"start_time": time(18, 0), "end_time": time(9, 0)}, "ck_schedule_rule_time_order"),
        ({"start_time": time(9, 0), "end_time": time(9, 0)}, "ck_schedule_rule_time_order"),
        ({"weekday": 7}, "ck_schedule_rule_weekday_range"),
        ({"weekday": -1}, "ck_schedule_rule_weekday_range"),
        ({"slot_duration_min": 0}, "ck_schedule_rule_slot_positive"),
        (
            {"valid_from": date(2026, 6, 2), "valid_to": date(2026, 6, 1)},
            "ck_schedule_rule_validity_order",
        ),
    ],
)
async def test_regla_invalida_viola_check(
    db_session: AsyncSession, overrides: dict[str, Any], constraint: str
) -> None:
    clinic, professional, chair = await _recursos(db_session)
    with pytest.raises(IntegrityError, match=constraint):
        await make_schedule_rule(db_session, clinic, professional, chair, **overrides)


async def test_regla_lunes_sin_fin_de_vigencia_persiste(db_session: AsyncSession) -> None:
    clinic, professional, chair = await _recursos(db_session)
    rule = await make_schedule_rule(db_session, clinic, professional, chair)
    await db_session.refresh(rule)
    assert rule.weekday == 0
    assert (rule.start_time, rule.end_time, rule.slot_duration_min) == (time(9), time(13), 30)
    assert rule.valid_to is None
    assert rule.active is True
    assert (rule.professional_id, rule.chair_id) == (professional.id, chair.id)


async def test_vigencia_de_un_solo_dia_es_valida(db_session: AsyncSession) -> None:
    clinic, professional, chair = await _recursos(db_session)
    dia = date(2026, 6, 1)
    await make_schedule_rule(db_session, clinic, professional, chair, valid_from=dia, valid_to=dia)


async def test_sillon_de_otra_clinica_viola_fk_compuesta(db_session: AsyncSession) -> None:
    clinic_a, professional_a, _ = await _recursos(db_session)
    clinic_b = await make_clinic(db_session)
    chair_b = await make_chair(db_session, clinic_b)
    with pytest.raises(IntegrityError, match="fk_schedule_rule_clinic_id_chair_id_chair"):
        await make_schedule_rule(db_session, clinic_a, professional_a, chair_b)


async def test_profesional_de_otra_clinica_viola_fk_compuesta(db_session: AsyncSession) -> None:
    clinic_a, _, chair_a = await _recursos(db_session)
    clinic_b = await make_clinic(db_session)
    professional_b = await make_professional(db_session, clinic_b)
    with pytest.raises(IntegrityError, match="fk_schedule_rule_clinic_id_professional_id"):
        await make_schedule_rule(db_session, clinic_a, professional_b, chair_a)


async def test_regla_sin_clinic_id_rechazada(db_session: AsyncSession) -> None:
    _, professional, chair = await _recursos(db_session)
    db_session.add(
        ScheduleRule(
            clinic_id=None,
            professional_id=professional.id,
            chair_id=chair.id,
            weekday=0,
            start_time=time(9),
            end_time=time(13),
            slot_duration_min=30,
            valid_from=date(2026, 1, 1),
        )
    )
    with pytest.raises(IntegrityError, match="clinic_id"):
        await db_session.flush()
