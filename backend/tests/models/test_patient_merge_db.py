"""Invariantes de base de la fusión de pacientes (C-06 tarea 1.1, D9)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.models import Patient, PatientMerge
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_clinic, make_patient, make_user

pytestmark = pytest.mark.integration

ARCHIVADO = datetime(2030, 1, 1, tzinfo=UTC)


async def test_fusionado_apunta_a_un_paciente_de_su_clinica(db_session: AsyncSession) -> None:
    clinic = await make_clinic(db_session)
    conservado = await make_patient(db_session, clinic)
    duplicado = await make_patient(db_session, clinic, full_name="Duplicado Ficticio")
    duplicado.archived_at = ARCHIVADO
    duplicado.merged_into_patient_id = conservado.id
    await db_session.flush()


async def test_fusionado_en_otra_clinica_viola_la_fk(db_session: AsyncSession) -> None:
    clinic = await make_clinic(db_session)
    otra = await make_clinic(db_session)
    ajeno = await make_patient(db_session, otra)
    duplicado = await make_patient(db_session, clinic)
    with pytest.raises(IntegrityError, match="fk_patient_merged_into_patient_id_clinic_id_patient"):
        async with db_session.begin_nested():
            duplicado.archived_at = ARCHIVADO
            duplicado.merged_into_patient_id = ajeno.id
            await db_session.flush()


@pytest.mark.parametrize(
    ("archivar", "a_si_mismo", "constraint"),
    [
        (False, False, "ck_patient_merged_is_archived"),
        (True, True, "ck_patient_not_merged_into_self"),
    ],
)
async def test_checks_de_fusion(
    db_session: AsyncSession, archivar: bool, a_si_mismo: bool, constraint: str
) -> None:
    clinic = await make_clinic(db_session)
    conservado = await make_patient(db_session, clinic)
    duplicado = await make_patient(db_session, clinic)
    with pytest.raises(IntegrityError, match=constraint):
        async with db_session.begin_nested():
            if archivar:
                duplicado.archived_at = ARCHIVADO
            duplicado.merged_into_patient_id = duplicado.id if a_si_mismo else conservado.id
            await db_session.flush()


async def _registro(db_session: AsyncSession) -> PatientMerge:
    clinic = await make_clinic(db_session)
    conservado: Patient = await make_patient(db_session, clinic)
    duplicado: Patient = await make_patient(db_session, clinic)
    registro = PatientMerge(
        clinic_id=clinic.id,
        source_patient_id=duplicado.id,
        target_patient_id=conservado.id,
        actor_user_id=(await make_user(db_session, clinic)).id,
        appointment_ids=[],
        filled_fields=[],
    )
    db_session.add(registro)
    await db_session.flush()
    return registro


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE patient_merge SET filled_fields = '[]'::jsonb WHERE id = :id",
        "DELETE FROM patient_merge WHERE id = :id",
    ],
)
async def test_registro_de_fusion_es_append_only(db_session: AsyncSession, sql: str) -> None:
    registro = await _registro(db_session)
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(text(sql), {"id": registro.id})


async def test_registro_con_paciente_de_otra_clinica_viola_la_fk(db_session: AsyncSession) -> None:
    clinic = await make_clinic(db_session)
    otra = await make_clinic(db_session)
    with pytest.raises(
        IntegrityError, match="fk_patient_merge_source_patient_id_clinic_id_patient"
    ):
        async with db_session.begin_nested():
            db_session.add(
                PatientMerge(
                    clinic_id=clinic.id,
                    source_patient_id=(await make_patient(db_session, otra)).id,
                    target_patient_id=(await make_patient(db_session, clinic)).id,
                    actor_user_id=(await make_user(db_session, clinic)).id,
                    appointment_ids=[],
                    filled_fields=[],
                )
            )
            await db_session.flush()
