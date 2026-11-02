"""Patient: contacto obligatorio, DNI no único, formato E.164 y tenant (Postgres real)."""

from typing import Any

import pytest
from app.models import Patient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_clinic, make_patient


async def test_paciente_sin_telefono_ni_email_viola_check(db_session: AsyncSession) -> None:
    clinic = await make_clinic(db_session)
    with pytest.raises(IntegrityError, match="ck_patient_contact_required"):
        await make_patient(db_session, clinic, phone_e164=None, email=None)


async def test_paciente_solo_con_email_persiste_sin_opt_in(db_session: AsyncSession) -> None:
    clinic = await make_clinic(db_session)
    patient = await make_patient(
        db_session, clinic, phone_e164=None, email="paciente.ficticio@example.com"
    )
    await db_session.refresh(patient)
    assert patient.phone_e164 is None
    assert patient.email == "paciente.ficticio@example.com"
    assert patient.whatsapp_opt_in is False
    assert patient.created_at is not None


async def test_paciente_solo_con_telefono_persiste(db_session: AsyncSession) -> None:
    clinic = await make_clinic(db_session)
    patient = await make_patient(db_session, clinic, phone_e164="+5491155550123", email=None)
    assert patient.email is None


async def test_dos_pacientes_con_el_mismo_dni_persisten(db_session: AsyncSession) -> None:
    clinic = await make_clinic(db_session)
    await make_patient(db_session, clinic, dni="00000000")
    await make_patient(db_session, clinic, full_name="Paciente Ficticio Dos", dni="00000000")


@pytest.mark.parametrize(
    "telefono",
    ["+54 9 11 5555 0123", "5491155550123", "+0491155550123", "+5491", "+549115555012345678"],
)
async def test_telefono_fuera_de_e164_viola_check(db_session: AsyncSession, telefono: str) -> None:
    clinic = await make_clinic(db_session)
    with pytest.raises(IntegrityError, match="ck_patient_phone_e164_format"):
        await make_patient(db_session, clinic, phone_e164=telefono)


@pytest.mark.parametrize("nombre", ["", "   "])
async def test_nombre_vacio_viola_check(db_session: AsyncSession, nombre: str) -> None:
    clinic = await make_clinic(db_session)
    with pytest.raises(IntegrityError, match="ck_patient_full_name_not_blank"):
        await make_patient(db_session, clinic, full_name=nombre)


async def test_paciente_sin_clinic_id_rechazado(db_session: AsyncSession) -> None:
    db_session.add(Patient(clinic_id=None, full_name="Paciente Ficticio", email="p@example.com"))
    with pytest.raises(IntegrityError, match="clinic_id"):
        await db_session.flush()


async def test_paciente_de_clinica_inexistente_viola_fk(db_session: AsyncSession) -> None:
    import uuid

    kwargs: dict[str, Any] = {"clinic_id": uuid.uuid4(), "full_name": "P", "email": "p@example.com"}
    db_session.add(Patient(**kwargs))
    with pytest.raises(IntegrityError, match="fk_patient_clinic_id_clinic"):
        await db_session.flush()
