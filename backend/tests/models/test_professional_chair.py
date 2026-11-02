"""Professional y Chair: tenant obligatorio, FK a clinic y CHECKs de duración."""

import uuid

import pytest
from app.models import Chair, Professional
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_chair, make_clinic, make_professional


async def test_professional_sin_clinic_id_rechazado(db_session: AsyncSession) -> None:
    db_session.add(Professional(clinic_id=None, display_name="Dr. Ficticio"))
    with pytest.raises(IntegrityError, match="clinic_id"):
        await db_session.flush()


async def test_chair_sin_clinic_id_rechazado(db_session: AsyncSession) -> None:
    db_session.add(Chair(clinic_id=None, name="Sillón Ficticio"))
    with pytest.raises(IntegrityError, match="clinic_id"):
        await db_session.flush()


async def test_professional_con_clinica_inexistente_rechazado_por_fk(
    db_session: AsyncSession,
) -> None:
    db_session.add(Professional(clinic_id=uuid.uuid4(), display_name="Dr. Ficticio"))
    with pytest.raises(IntegrityError, match="fk_professional_clinic_id_clinic"):
        await db_session.flush()


async def test_chair_con_clinica_inexistente_rechazado_por_fk(db_session: AsyncSession) -> None:
    db_session.add(Chair(clinic_id=uuid.uuid4(), name="Sillón Ficticio"))
    with pytest.raises(IntegrityError, match="fk_chair_clinic_id_clinic"):
        await db_session.flush()


@pytest.mark.parametrize(
    ("campo", "valor", "constraint"),
    [
        ("default_duration_min", 0, "ck_professional_default_duration_positive"),
        ("default_duration_min", -15, "ck_professional_default_duration_positive"),
        ("buffer_min", -1, "ck_professional_buffer_nonneg"),
    ],
)
async def test_professional_duraciones_invalidas_violan_check(
    db_session: AsyncSession, campo: str, valor: int, constraint: str
) -> None:
    clinic = await make_clinic(db_session)
    db_session.add(Professional(clinic_id=clinic.id, display_name="Dr. Ficticio", **{campo: valor}))
    with pytest.raises(IntegrityError, match=constraint):
        await db_session.flush()


async def test_professional_valido_toma_defaults(db_session: AsyncSession) -> None:
    clinic = await make_clinic(db_session)
    professional = await make_professional(db_session, clinic, buffer_min=0)
    await db_session.refresh(professional)
    assert professional.active is True
    assert professional.booking_enabled is True
    assert professional.buffer_min == 0
    assert professional.default_duration_min > 0


async def test_chair_valido_nace_activo(db_session: AsyncSession) -> None:
    clinic = await make_clinic(db_session)
    chair = await make_chair(db_session, clinic)
    await db_session.refresh(chair)
    assert chair.active is True
