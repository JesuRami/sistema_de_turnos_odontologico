"""Los errores de dominio de pacientes nunca exponen nombre, teléfono ni email (regla 13)."""

import pytest
from app.common.exceptions import DomainError
from app.models import Patient
from app.modules.clinic.service import create_patient, persist_patient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_clinic

NOMBRE = "Zoila Inventada Ficticia"
TELEFONO_MALO = "+54 9 11 5555 0123"  # con espacios: la base lo rechaza por formato
EMAIL = "zoila.inventada@example.com"
DNI = "00000000"


def _sin_pii(error: DomainError) -> None:
    expuesto = f"{error!s} {error.detail} {error!r}"
    for dato in (NOMBRE, "Zoila", TELEFONO_MALO, "5555", "0123", EMAIL, "inventada", DNI):
        assert dato not in expuesto, dato
    assert error.__cause__ is None


async def test_sin_contacto_da_error_de_dominio_sin_pii(db_session: AsyncSession) -> None:
    clinic = await make_clinic(db_session)
    with pytest.raises(DomainError) as exc:
        await create_patient(db_session, clinic.id, full_name=NOMBRE, dni=DNI)
    assert exc.value.status_code == 422
    _sin_pii(exc.value)


async def test_formato_de_telefono_en_la_base_da_error_sin_pii(db_session: AsyncSession) -> None:
    clinic = await make_clinic(db_session)
    crudo = Patient(clinic_id=clinic.id, full_name=NOMBRE, phone_e164=TELEFONO_MALO, email=EMAIL)
    with pytest.raises(DomainError) as exc:
        await persist_patient(db_session, crudo)
    assert exc.value.status_code == 422
    _sin_pii(exc.value)


async def test_telefono_invalido_de_entrada_da_error_sin_pii(db_session: AsyncSession) -> None:
    clinic = await make_clinic(db_session)
    with pytest.raises(DomainError) as exc:
        await create_patient(db_session, clinic.id, full_name=NOMBRE, phone="12ab", email=EMAIL)
    assert exc.value.status_code == 422
    _sin_pii(exc.value)


async def test_tras_el_error_la_sesion_sigue_usable_y_no_queda_nada(
    db_session: AsyncSession,
) -> None:
    clinic = await make_clinic(db_session)
    with pytest.raises(DomainError):
        await create_patient(db_session, clinic.id, full_name=NOMBRE)

    paciente = await create_patient(
        db_session, clinic.id, full_name=NOMBRE, phone="011 15 5555-0123"
    )

    assert paciente.phone_e164 == "+5491155550123"
    total = await db_session.scalar(select(func.count()).select_from(Patient))
    assert total == 1
