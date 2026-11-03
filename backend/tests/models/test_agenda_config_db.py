"""Invariantes de base de C-04: anti-solape de reglas, políticas, bloqueos y auditoría."""

from datetime import date, time, timedelta
from typing import Any

import pytest
from app.models import AgendaConfigEvent, Block, ConfigAction, ConfigEntity
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import (
    make_block,
    make_chair,
    make_clinic,
    make_professional,
    make_schedule_rule,
    make_user,
)

pytestmark = pytest.mark.integration

_EXCLUDE = "ex_schedule_rule_no_overlap"


async def _base(db_session: AsyncSession) -> dict[str, Any]:
    clinic = await make_clinic(db_session)
    return {
        "clinic": clinic,
        "professional": await make_professional(db_session, clinic),
        "chair": await make_chair(db_session, clinic),
        "user": await make_user(db_session, clinic),
    }


async def _regla(db_session: AsyncSession, base: dict[str, Any], **overrides: Any) -> None:
    await make_schedule_rule(
        db_session, base["clinic"], base["professional"], base["chair"], **overrides
    )


# ------------------------------------------------------------ schedule_rule


@pytest.mark.parametrize(
    "nueva",
    [
        {"start_time": time(12, 0), "end_time": time(15, 0)},
        {"start_time": time(8, 0), "end_time": time(9, 30)},
        {"start_time": time(10, 0), "end_time": time(11, 0)},
        {"valid_from": date(2027, 1, 1)},
    ],
)
async def test_regla_solapada_rechazada_por_la_base(
    db_session: AsyncSession, nueva: dict[str, Any]
) -> None:
    """WHEN franja y vigencia se intersectan (mismo prof/sillón/día) THEN viola el EXCLUDE."""
    base = await _base(db_session)
    await _regla(db_session, base)  # lunes 09-13 desde 2026-01-01, sin fin

    with pytest.raises(IntegrityError, match=_EXCLUDE):
        async with db_session.begin_nested():
            await _regla(db_session, base, **nueva)


@pytest.mark.parametrize(
    "nueva",
    [
        {"start_time": time(13, 0), "end_time": time(17, 0)},
        {"weekday": 1},
        {"active": False},
    ],
)
async def test_reglas_que_no_colisionan_conviven(
    db_session: AsyncSession, nueva: dict[str, Any]
) -> None:
    """WHEN franja contigua, otro día o regla inactiva THEN ambas persisten."""
    base = await _base(db_session)
    await _regla(db_session, base)
    await _regla(db_session, base, **nueva)


async def test_vigencias_disjuntas_conviven(db_session: AsyncSession) -> None:
    """WHEN la primera vence el 2026-06-30 y la segunda arranca el 2026-07-01 THEN conviven."""
    base = await _base(db_session)
    await _regla(db_session, base, valid_to=date(2026, 6, 30))
    await _regla(db_session, base, valid_from=date(2026, 7, 1))


async def test_vigencia_inclusiva_en_el_ultimo_dia(db_session: AsyncSession) -> None:
    """WHEN la primera vence el 2026-06-30 y la segunda arranca ese mismo día THEN colisiona."""
    base = await _base(db_session)
    await _regla(db_session, base, valid_to=date(2026, 6, 30))
    with pytest.raises(IntegrityError, match=_EXCLUDE):
        async with db_session.begin_nested():
            await _regla(db_session, base, valid_from=date(2026, 6, 30))


async def test_otro_sillon_no_colisiona(db_session: AsyncSession) -> None:
    """WHEN mismo profesional y franja en otro sillón THEN persiste (US-002 CA-2: por par)."""
    base = await _base(db_session)
    await _regla(db_session, base)
    otro = await make_chair(db_session, base["clinic"], name="Sillón Ficticio Dos")
    await make_schedule_rule(db_session, base["clinic"], base["professional"], otro)


async def test_reactivar_regla_solapada_rechazado(db_session: AsyncSession) -> None:
    """WHEN se reactiva una regla que solapa con una activa THEN viola el EXCLUDE."""
    base = await _base(db_session)
    await _regla(db_session, base)
    inactiva = await make_schedule_rule(
        db_session, base["clinic"], base["professional"], base["chair"], active=False
    )
    with pytest.raises(IntegrityError, match=_EXCLUDE):
        async with db_session.begin_nested():
            inactiva.active = True
            await db_session.flush()


# ------------------------------------------------------------------- clinic


async def test_politicas_nuevas_con_defaults(db_session: AsyncSession) -> None:
    clinic = await make_clinic(db_session)
    await db_session.refresh(clinic)
    assert clinic.max_overbookings_per_day == 2
    assert clinic.waitlist_offer_ttl_hours == 4


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"max_overbookings_per_day": -1}, "ck_clinic_max_overbookings_nonneg"),
        ({"waitlist_offer_ttl_hours": 0}, "ck_clinic_waitlist_offer_ttl_positive"),
    ],
)
async def test_politicas_invalidas_violan_check(
    db_session: AsyncSession, overrides: dict[str, Any], constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        async with db_session.begin_nested():
            await make_clinic(db_session, **overrides)


# -------------------------------------------------------------------- block


async def test_bloqueo_valido_persiste_con_motivo(db_session: AsyncSession) -> None:
    base = await _base(db_session)
    block = await make_block(db_session, base["clinic"], professional=base["professional"])
    await db_session.refresh(block)
    assert block.reason.value == "vacaciones"
    assert block.chair_id is None
    assert block.removed_at is None


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"professional_id": None, "chair_id": None}, "ck_block_has_target"),
        ({"ends_at_delta": timedelta(0)}, "ck_block_range_order"),
        ({"ends_at_delta": timedelta(hours=-1)}, "ck_block_range_order"),
    ],
)
async def test_bloqueo_invalido_viola_check(
    db_session: AsyncSession, overrides: dict[str, Any], constraint: str
) -> None:
    base = await _base(db_session)
    with pytest.raises(IntegrityError, match=constraint):
        async with db_session.begin_nested():
            await make_block(db_session, base["clinic"], chair=base["chair"], **overrides)


async def test_bloqueo_con_motivo_fuera_de_catalogo_rechazado(db_session: AsyncSession) -> None:
    base = await _base(db_session)
    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "INSERT INTO block (clinic_id, chair_id, starts_at, ends_at, reason, "
                    "created_by_user_id) VALUES (:c, :ch, now(), now() + interval '1 hour', "
                    "'siesta', :u)"
                ),
                {"c": base["clinic"].id, "ch": base["chair"].id, "u": base["user"].id},
            )


async def test_bloqueo_con_sillon_de_otra_clinica_viola_fk(db_session: AsyncSession) -> None:
    base = await _base(db_session)
    otra = await make_clinic(db_session)
    sillon_ajeno = await make_chair(db_session, otra)
    with pytest.raises(IntegrityError, match="fk_block_clinic_id_chair_id_chair"):
        async with db_session.begin_nested():
            await make_block(db_session, base["clinic"], chair=sillon_ajeno)


# ------------------------------------------------------- agenda_config_event


async def _evento(db_session: AsyncSession) -> AgendaConfigEvent:
    clinic = await make_clinic(db_session)
    actor = await make_user(db_session, clinic)
    evento = AgendaConfigEvent(
        clinic_id=clinic.id,
        actor_user_id=actor.id,
        entity=ConfigEntity.CLINIC_POLICY,
        entity_id=clinic.id,
        action=ConfigAction.UPDATED,
        changes={"cancellation_window_hours": [24, 48]},
    )
    db_session.add(evento)
    await db_session.flush()
    return evento


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE agenda_config_event SET changes = '{}'::jsonb WHERE id = :id",
        "DELETE FROM agenda_config_event WHERE id = :id",
    ],
)
async def test_auditoria_de_configuracion_es_append_only(
    db_session: AsyncSession, sql: str
) -> None:
    evento = await _evento(db_session)
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(text(sql), {"id": evento.id})


def test_bloque_no_tiene_borrado_fisico_en_el_modelo() -> None:
    """El modelo expone baja lógica (`removed_at`), no un flag de borrado físico."""
    assert {"removed_at", "removed_by_user_id"} <= set(Block.__table__.columns.keys())
