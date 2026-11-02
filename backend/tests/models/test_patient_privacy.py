"""Resguardos mínimos de datos personales: consentimiento coherente y archivado lógico."""

from datetime import UTC, datetime

import pytest
from app.models import Patient
from app.modules.clinic.service import find_patients_by_phone
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_clinic, make_patient

CELULAR = "+5491155550123"


async def test_version_de_consentimiento_sin_fecha_viola_check(db_session: AsyncSession) -> None:
    clinic = await make_clinic(db_session)
    with pytest.raises(IntegrityError, match="ck_patient_consent_coherent"):
        await make_patient(db_session, clinic, privacy_consent_version="v1")


async def test_consentimiento_con_fecha_y_version_persiste(db_session: AsyncSession) -> None:
    clinic = await make_clinic(db_session)
    ahora = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
    patient = await make_patient(
        db_session, clinic, privacy_consent_at=ahora, privacy_consent_version="v1"
    )
    await db_session.refresh(patient)
    assert patient.privacy_consent_at == ahora
    assert patient.privacy_consent_version == "v1"


async def test_paciente_sin_consentimiento_ni_archivo_por_defecto(db_session: AsyncSession) -> None:
    clinic = await make_clinic(db_session)
    patient = await make_patient(db_session, clinic)
    await db_session.refresh(patient)
    assert patient.privacy_consent_at is None
    assert patient.privacy_consent_version is None
    assert patient.archived_at is None


async def test_paciente_archivado_no_aparece_en_el_match_pero_la_fila_persiste(
    db_session: AsyncSession,
) -> None:
    clinic = await make_clinic(db_session)
    archivado = await make_patient(db_session, clinic, phone_e164=CELULAR)
    vigente = await make_patient(
        db_session, clinic, full_name="Paciente Ficticio Dos", phone_e164=CELULAR
    )
    archivado.archived_at = datetime(2026, 11, 2, tzinfo=UTC)
    await db_session.flush()

    encontrados = await find_patients_by_phone(db_session, clinic.id, CELULAR)

    assert [p.id for p in encontrados] == [vigente.id]
    assert await db_session.get(Patient, archivado.id) is not None
