"""Clínica: slug único global, defaults y CHECKs (Postgres real)."""

import pytest
from app.models import Clinic
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import unique_slug


async def test_clinica_con_solo_name_y_slug_toma_defaults(db_session: AsyncSession) -> None:
    clinic = Clinic(name="Clínica Ficticia Uno", slug=unique_slug())
    db_session.add(clinic)
    await db_session.flush()
    await db_session.refresh(clinic)

    assert clinic.timezone == "America/Argentina/Buenos_Aires"
    assert clinic.cancellation_window_hours == 24
    assert clinic.booking_enabled is False
    assert clinic.reminder_steps == [
        {"offset_h": 72, "channel": "whatsapp"},
        {"offset_h": 24, "channel": "whatsapp"},
        {"offset_h": 3, "channel": "whatsapp"},
    ]
    assert clinic.created_at is not None


async def test_slug_duplicado_rechazado_por_la_base(db_session: AsyncSession) -> None:
    slug = unique_slug()
    db_session.add(Clinic(name="Clínica Ficticia A", slug=slug))
    await db_session.flush()

    db_session.add(Clinic(name="Clínica Ficticia B", slug=slug))
    with pytest.raises(IntegrityError, match="uq_clinic_slug"):
        await db_session.flush()


async def test_slugs_distintos_conviven(db_session: AsyncSession) -> None:
    db_session.add_all(
        [
            Clinic(name="Clínica Ficticia A", slug="clinica-demo"),
            Clinic(name="Clínica Ficticia B", slug="clinica-demo-2"),
        ]
    )
    await db_session.flush()  # sin excepción: ambas persisten


async def test_ventana_de_cancelacion_negativa_viola_check(db_session: AsyncSession) -> None:
    db_session.add(
        Clinic(name="Clínica Ficticia", slug=unique_slug(), cancellation_window_hours=-1)
    )
    with pytest.raises(IntegrityError, match="ck_clinic_cancellation_window_nonneg"):
        await db_session.flush()


async def test_ventana_de_cancelacion_cero_es_valida(db_session: AsyncSession) -> None:
    db_session.add(Clinic(name="Clínica Ficticia", slug=unique_slug(), cancellation_window_hours=0))
    await db_session.flush()


@pytest.mark.parametrize("valor", [{"offset_h": 24}, "texto", 7])
async def test_reminder_steps_no_array_viola_check(db_session: AsyncSession, valor: object) -> None:
    db_session.add(Clinic(name="Clínica Ficticia", slug=unique_slug(), reminder_steps=valor))
    with pytest.raises(IntegrityError, match="ck_clinic_reminder_steps_array"):
        await db_session.flush()
