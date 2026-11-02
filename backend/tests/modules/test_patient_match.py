"""find_patients_by_phone: normaliza la entrada y no cruza clínicas."""

from datetime import UTC, datetime

import pytest
from app.common.phone import InvalidPhoneError
from app.modules.clinic.service import find_patients_by_phone
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_clinic, make_patient

CELULAR = "+5491155550123"


async def test_match_con_formato_distinto_al_guardado(db_session: AsyncSession) -> None:
    clinic = await make_clinic(db_session)
    patient = await make_patient(db_session, clinic, phone_e164=CELULAR)

    for escrito in ("011 15 5555-0123", "+54 9 11 5555-0123", CELULAR):
        encontrados = await find_patients_by_phone(db_session, clinic.id, escrito)
        assert [p.id for p in encontrados] == [patient.id]


async def test_telefono_compartido_devuelve_ambos_mas_reciente_primero(
    db_session: AsyncSession,
) -> None:
    clinic = await make_clinic(db_session)
    viejo = await make_patient(
        db_session, clinic, phone_e164=CELULAR, created_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    nuevo = await make_patient(
        db_session,
        clinic,
        full_name="Paciente Ficticio Dos",
        phone_e164=CELULAR,
        created_at=datetime(2026, 2, 1, tzinfo=UTC),
    )

    encontrados = await find_patients_by_phone(db_session, clinic.id, CELULAR)

    assert [p.id for p in encontrados] == [nuevo.id, viejo.id]


async def test_sin_coincidencias_devuelve_lista_vacia(db_session: AsyncSession) -> None:
    clinic = await make_clinic(db_session)
    await make_patient(db_session, clinic, phone_e164=CELULAR)

    assert await find_patients_by_phone(db_session, clinic.id, "+5491155550999") == []


async def test_mismo_telefono_en_otra_clinica_no_se_devuelve(db_session: AsyncSession) -> None:
    clinic_a = await make_clinic(db_session)
    clinic_b = await make_clinic(db_session)
    paciente_a = await make_patient(db_session, clinic_a, phone_e164=CELULAR)
    await make_patient(db_session, clinic_b, phone_e164=CELULAR)

    encontrados = await find_patients_by_phone(db_session, clinic_a.id, CELULAR)

    assert [p.id for p in encontrados] == [paciente_a.id]
    assert {p.clinic_id for p in encontrados} == {clinic_a.id}


async def test_telefono_invalido_propaga_error_sin_el_valor(db_session: AsyncSession) -> None:
    clinic = await make_clinic(db_session)
    with pytest.raises(InvalidPhoneError) as exc:
        await find_patients_by_phone(db_session, clinic.id, "12ab")
    assert "12ab" not in str(exc.value)
