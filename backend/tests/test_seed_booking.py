"""Seed de la clínica demo reservable (C-07): opt-in por entorno, idempotente, datos ficticios."""

import pytest
from app.models import Chair, Clinic, Professional, ScheduleRule
from app.seed import SeedConfig, read_seed_config, seed_clinic
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

CLAVE = "clave-seed-de-prueba-no-real-7"
ENV = {
    "SEED_CLINIC_SLUG": "clinica-demo-ficticia",
    "SEED_CLINIC_NAME": "Clínica Demo Ficticia",
    "SEED_ADMIN_EMAIL": "admin@example.com",
    "SEED_ADMIN_PASSWORD": CLAVE,
}


def _config(slug: str = "clinica-demo-ficticia", *, demo: bool = True) -> SeedConfig:
    return SeedConfig(
        clinic_slug=slug,
        clinic_name="Clínica Demo Ficticia",
        admin_email="admin@example.com",
        admin_password=CLAVE,
        booking_demo=demo,
    )


async def _contar(session: AsyncSession, modelo: type, clinic_id: object) -> int:
    total = await session.scalar(
        select(func.count()).select_from(modelo).where(modelo.clinic_id == clinic_id)  # type: ignore[attr-defined]
    )
    return int(total or 0)


async def test_la_clinica_demo_queda_reservable(db_session: AsyncSession) -> None:
    await seed_clinic(db_session, _config())

    clinic = (
        await db_session.execute(select(Clinic).where(Clinic.slug == "clinica-demo-ficticia"))
    ).scalar_one()
    assert clinic.booking_enabled is True
    profesional = (
        await db_session.execute(select(Professional).where(Professional.clinic_id == clinic.id))
    ).scalar_one()
    assert profesional.active is True
    assert profesional.booking_enabled is True
    sillon = (
        await db_session.execute(select(Chair).where(Chair.clinic_id == clinic.id))
    ).scalar_one()
    reglas = (
        (await db_session.execute(select(ScheduleRule).where(ScheduleRule.clinic_id == clinic.id)))
        .scalars()
        .all()
    )
    assert sorted(r.weekday for r in reglas) == [0, 1, 2, 3, 4]
    assert all(r.active and r.chair_id == sillon.id for r in reglas)
    assert all(r.professional_id == profesional.id for r in reglas)
    assert all(r.valid_to is None for r in reglas)


async def test_reejecutar_el_seed_demo_es_idempotente(db_session: AsyncSession) -> None:
    await seed_clinic(db_session, _config())
    clinic_id = await db_session.scalar(
        select(Clinic.id).where(Clinic.slug == "clinica-demo-ficticia")
    )

    await seed_clinic(db_session, _config())

    assert (
        await db_session.scalar(
            select(func.count()).select_from(Clinic).where(Clinic.slug == "clinica-demo-ficticia")
        )
        == 1
    )
    assert await _contar(db_session, Professional, clinic_id) == 1
    assert await _contar(db_session, Chair, clinic_id) == 1
    assert await _contar(db_session, ScheduleRule, clinic_id) == 5


async def test_sin_el_flag_la_clinica_no_queda_publica(db_session: AsyncSession) -> None:
    await seed_clinic(db_session, _config("clinica-privada-ficticia", demo=False))

    clinic = (
        await db_session.execute(select(Clinic).where(Clinic.slug == "clinica-privada-ficticia"))
    ).scalar_one()
    assert clinic.booking_enabled is False
    assert await _contar(db_session, ScheduleRule, clinic.id) == 0


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [("true", True), ("1", True), ("TRUE", True), ("false", False), ("", False), (None, False)],
)
def test_el_flag_se_lee_del_entorno(valor: str | None, esperado: bool) -> None:
    entorno = dict(ENV)
    if valor is not None:
        entorno["SEED_BOOKING_DEMO"] = valor

    assert read_seed_config(entorno).booking_demo is esperado
