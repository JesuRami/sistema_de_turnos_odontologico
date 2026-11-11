"""Esquema clínico de C-15 contra Postgres real (D1, D2; reglas 4, 9 y 13).

Las invariantes las impone la base: `clinic_id` obligatorio, una ficha por paciente, numeración FDI,
coherencia de correcciones y FKs compuestas que impiden mezclar clínicas. SQL directo sobre las
tablas (no depende de los modelos ORM). Datos sintéticos.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import (
    make_appointment,
    make_chair,
    make_clinic,
    make_patient,
    make_professional,
    make_user,
)

pytestmark = pytest.mark.integration

CLINICAL_TABLES = (
    "clinical_record",
    "anamnesis_version",
    "odontogram_condition",
    "odontogram_event",
    "clinical_evolution",
    "clinical_attachment",
    "clinical_attachment_removal",
    "treatment_plan",
    "treatment_plan_version",
    "treatment_plan_item",
    "treatment_plan_decision",
    "clinical_access_event",
)
HASH = "a" * 64
INICIO = datetime(2030, 1, 7, 13, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Escena:
    clinic_id: uuid.UUID
    user_id: uuid.UUID
    professional_id: uuid.UUID
    patient_id: uuid.UUID
    appointment_id: uuid.UUID
    record_id: uuid.UUID


async def _sql(session: AsyncSession, sql: str, params: Mapping[str, Any] | None = None) -> Any:
    return (await session.execute(text(sql), dict(params or {}))).scalar()


async def _escena(session: AsyncSession) -> Escena:
    clinic = await make_clinic(session)
    user = await make_user(session, clinic)
    professional = await make_professional(session, clinic)
    chair = await make_chair(session, clinic)
    patient = await make_patient(session, clinic, full_name="Paciente Prueba Ficticio")
    turno = await make_appointment(
        session,
        clinic,
        patient=patient,
        professional=professional,
        chair=chair,
        starts_at=INICIO,
        created_by_user_id=user.id,
    )
    record_id = await _sql(
        session,
        "INSERT INTO clinical_record (clinic_id, patient_id, created_by_user_id) "
        "VALUES (:c, :p, :u) RETURNING id",
        {"c": clinic.id, "p": patient.id, "u": user.id},
    )
    return Escena(clinic.id, user.id, professional.id, patient.id, turno.id, record_id)


async def _falla(session: AsyncSession, sql: str, params: Mapping[str, Any], match: str) -> None:
    with pytest.raises((IntegrityError, DBAPIError), match=match):
        async with session.begin_nested():
            await session.execute(text(sql), dict(params))


async def _evento(session: AsyncSession, e: Escena, tooth: int, surface: str = "O") -> Any:
    return await _sql(
        session,
        "INSERT INTO odontogram_event (clinic_id, record_id, tooth, surface, professional_id, "
        "created_by_user_id) VALUES (:c, :r, :t, CAST(:s AS tooth_surface), :pr, :u) RETURNING id",
        {
            "c": e.clinic_id,
            "r": e.record_id,
            "t": tooth,
            "s": surface,
            "pr": e.professional_id,
            "u": e.user_id,
        },
    )


async def test_todas_las_tablas_clinicas_tienen_clinic_id_obligatorio(
    db_session: AsyncSession,
) -> None:
    filas = (
        await db_session.execute(
            text(
                "SELECT table_name, is_nullable FROM information_schema.columns "
                "WHERE table_schema = 'public' AND column_name = 'clinic_id' "
                "AND table_name = ANY(:tablas)"
            ),
            {"tablas": list(CLINICAL_TABLES)},
        )
    ).all()

    assert {fila[0]: fila[1] for fila in filas} == {tabla: "NO" for tabla in CLINICAL_TABLES}


async def test_una_sola_ficha_por_paciente(db_session: AsyncSession) -> None:
    e = await _escena(db_session)

    await _falla(
        db_session,
        "INSERT INTO clinical_record (clinic_id, patient_id, created_by_user_id) "
        "VALUES (:c, :p, :u)",
        {"c": e.clinic_id, "p": e.patient_id, "u": e.user_id},
        "uq_clinical_record_clinic_id_patient_id",
    )


@pytest.mark.parametrize("tooth", [11, 18, 21, 28, 31, 38, 41, 48, 51, 55, 61, 65, 71, 75, 81, 85])
async def test_piezas_fdi_validas_se_aceptan(db_session: AsyncSession, tooth: int) -> None:
    e = await _escena(db_session)

    assert await _evento(db_session, e, tooth) is not None


@pytest.mark.parametrize("tooth", [0, 10, 19, 20, 49, 50, 56, 66, 86, 99])
async def test_piezas_fuera_de_rango_se_rechazan(db_session: AsyncSession, tooth: int) -> None:
    e = await _escena(db_session)

    with pytest.raises((IntegrityError, DBAPIError), match="ck_odontogram_event_fdi_tooth"):
        async with db_session.begin_nested():
            await _evento(db_session, e, tooth)


async def test_cara_invalida_se_rechaza(db_session: AsyncSession) -> None:
    e = await _escena(db_session)

    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await _evento(db_session, e, 36, "X")


async def test_item_de_presupuesto_valida_fdi(db_session: AsyncSession) -> None:
    e = await _escena(db_session)
    plan = await _sql(
        db_session,
        "INSERT INTO treatment_plan (clinic_id, record_id, title, created_by_user_id) "
        "VALUES (:c, :r, 'Plan ficticio', :u) RETURNING id",
        {"c": e.clinic_id, "r": e.record_id, "u": e.user_id},
    )
    version = await _sql(
        db_session,
        "INSERT INTO treatment_plan_version (clinic_id, plan_id, version, created_by_user_id) "
        "VALUES (:c, :p, 1, :u) RETURNING id",
        {"c": e.clinic_id, "p": plan, "u": e.user_id},
    )
    sql = (
        "INSERT INTO treatment_plan_item (clinic_id, version_id, phase, position, description, "
        "quantity, unit_price_cents, tooth) VALUES (:c, :v, 1, :pos, 'Item ficticio', 1, 100, :t)"
    )
    await db_session.execute(text(sql), {"c": e.clinic_id, "v": version, "pos": 1, "t": 36})

    await _falla(db_session, sql, {"c": e.clinic_id, "v": version, "pos": 2, "t": 49}, "fdi_tooth")


async def _evolucion(session: AsyncSession, e: Escena, **campos: Any) -> Any:
    valores: dict[str, Any] = {
        "c": e.clinic_id,
        "r": e.record_id,
        "pr": e.professional_id,
        "u": e.user_id,
        "kind": "entry",
        "corr": None,
        "reason": None,
        "body": "Evolución sintética de prueba",
        "appt": None,
        "now": INICIO,
        "h": HASH,
    }
    valores.update(campos)
    return await _sql(
        session,
        "INSERT INTO clinical_evolution (clinic_id, record_id, appointment_id, professional_id, "
        "created_by_user_id, kind, corrects_evolution_id, reason, body, signed_at, "
        "content_sha256) VALUES (:c, :r, :appt, :pr, :u, CAST(:kind AS evolution_kind), :corr, "
        ":reason, :body, :now, :h) RETURNING id",
        valores,
    )


async def test_correccion_exige_original_y_motivo(db_session: AsyncSession) -> None:
    e = await _escena(db_session)
    original = await _evolucion(db_session, e)

    with pytest.raises((IntegrityError, DBAPIError), match="correction_coherent"):
        async with db_session.begin_nested():
            await _evolucion(db_session, e, kind="correction", reason="Motivo ficticio largo")
    with pytest.raises((IntegrityError, DBAPIError), match="correction_coherent"):
        async with db_session.begin_nested():
            await _evolucion(db_session, e, corr=original, reason="Motivo ficticio largo")
    correccion = await _evolucion(
        db_session, e, kind="correction", corr=original, reason="Motivo ficticio largo"
    )

    assert correccion is not None


@pytest.mark.parametrize("body", ["", "x" * 4001])
async def test_cuerpo_de_evolucion_acotado(db_session: AsyncSession, body: str) -> None:
    e = await _escena(db_session)

    with pytest.raises((IntegrityError, DBAPIError), match="body_length"):
        async with db_session.begin_nested():
            await _evolucion(db_session, e, body=body)


async def test_fk_compuesta_impide_mezclar_clinicas(db_session: AsyncSession) -> None:
    """Escenario "FK compuesta impide mezclar clínicas"."""
    a = await _escena(db_session)
    b = await _escena(db_session)

    with pytest.raises(IntegrityError, match="fk_clinical_evolution_appointment"):
        async with db_session.begin_nested():
            await _evolucion(db_session, a, appt=b.appointment_id)
    await _falla(
        db_session,
        "INSERT INTO clinical_record (clinic_id, patient_id, created_by_user_id) "
        "VALUES (:c, :p, :u)",
        {"c": a.clinic_id, "p": b.patient_id, "u": a.user_id},
        "fk_clinical_record_patient",
    )


async def test_registro_de_acceso_no_admite_texto_libre(db_session: AsyncSession) -> None:
    e = await _escena(db_session)
    sql = (
        "INSERT INTO clinical_access_event (clinic_id, record_id, actor_user_id, action, payload) "
        "VALUES (:c, :r, :u, 'record_read', CAST(:p AS jsonb))"
    )
    params = {"c": e.clinic_id, "r": e.record_id, "u": e.user_id}
    await db_session.execute(
        text(sql), {**params, "p": json.dumps({"version": 2, "id": str(uuid.uuid4())})}
    )

    await _falla(
        db_session, sql, {**params, "p": '{"nota": "Paciente Prueba Ficticio"}'}, "payload_safe"
    )
    await _falla(db_session, sql, {**params, "p": '{"x": {"y": 1}}'}, "payload_safe")
