"""Invariantes de base de `appointment` (C-05, regla dura 1): EXCLUDE, CHECKs y FKs intra-tenant.

Se insertan filas directo (sin servicio): la base debe defender la agenda sola.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.models import (
    AppointmentOrigin,
    AppointmentStatus,
    CancellationReason,
    Chair,
    Clinic,
    Patient,
    Professional,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import (
    make_appointment,
    make_chair,
    make_clinic,
    make_patient,
    make_professional,
)

pytestmark = pytest.mark.integration

EX_PROFESIONAL = "ex_appointment_professional_no_overlap"
EX_SILLON = "ex_appointment_chair_no_overlap"
T10 = datetime(2030, 1, 7, 13, 0, tzinfo=UTC)  # lunes 10:00 en Buenos Aires


async def _base(db_session: AsyncSession) -> dict[str, Any]:
    clinic = await make_clinic(db_session)
    return {
        "clinic": clinic,
        "patient": await make_patient(db_session, clinic),
        "professional": await make_professional(db_session, clinic),
        "otro_profesional": await make_professional(
            db_session, clinic, display_name="Dra. Ficticia Dos"
        ),
        "chair": await make_chair(db_session, clinic),
        "otro_sillon": await make_chair(db_session, clinic, name="Sillón Ficticio Dos"),
    }


async def _turno(
    db_session: AsyncSession,
    base: dict[str, Any],
    *,
    starts_at: datetime = T10,
    professional: Professional | None = None,
    chair: Chair | None = None,
    **overrides: Any,
) -> None:
    clinic: Clinic = base["clinic"]
    patient: Patient = base["patient"]
    await make_appointment(
        db_session,
        clinic,
        patient=patient,
        professional=professional or base["professional"],
        chair=chair or base["chair"],
        starts_at=starts_at,
        **overrides,
    )


# ------------------------------------------------------------------ EXCLUDE


async def test_mismo_profesional_en_otro_sillon_solapado_viola_el_exclude(
    db_session: AsyncSession,
) -> None:
    base = await _base(db_session)
    await _turno(db_session, base)
    with pytest.raises(IntegrityError, match=EX_PROFESIONAL):
        async with db_session.begin_nested():
            await _turno(
                db_session, base, starts_at=T10 + timedelta(minutes=15), chair=base["otro_sillon"]
            )


async def test_mismo_sillon_con_otro_profesional_viola_el_exclude(
    db_session: AsyncSession,
) -> None:
    base = await _base(db_session)
    await _turno(db_session, base)
    with pytest.raises(IntegrityError, match=EX_SILLON):
        async with db_session.begin_nested():
            await _turno(db_session, base, professional=base["otro_profesional"])


async def test_turnos_contiguos_conviven(db_session: AsyncSession) -> None:
    base = await _base(db_session)
    await _turno(db_session, base)
    await _turno(db_session, base, starts_at=T10 + timedelta(minutes=30))


async def test_el_buffer_integra_el_rango_ocupado(db_session: AsyncSession) -> None:
    base = await _base(db_session)
    await _turno(db_session, base, buffer_min=10)
    with pytest.raises(IntegrityError, match=EX_PROFESIONAL):
        async with db_session.begin_nested():
            await _turno(
                db_session, base, starts_at=T10 + timedelta(minutes=35), chair=base["otro_sillon"]
            )


@pytest.mark.parametrize(
    "estado", [AppointmentStatus.CANCELLED, AppointmentStatus.ABSENT, AppointmentStatus.NO_SHOW]
)
async def test_estados_terminales_liberan_el_hueco(
    db_session: AsyncSession, estado: AppointmentStatus
) -> None:
    base = await _base(db_session)
    extra: dict[str, Any] = {"status": estado}
    if estado == AppointmentStatus.CANCELLED:
        extra |= {
            "cancelled_at": T10 - timedelta(days=1),
            "cancellation_reason": CancellationReason.PACIENTE,
        }
    await _turno(db_session, base, **extra)
    await _turno(db_session, base)


@pytest.mark.parametrize(
    "estado", [AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED, AppointmentStatus.PRESENT]
)
async def test_estados_vigentes_ocupan_el_hueco(
    db_session: AsyncSession, estado: AppointmentStatus
) -> None:
    base = await _base(db_session)
    await _turno(db_session, base, status=estado)
    with pytest.raises(IntegrityError, match="ex_appointment_"):
        async with db_session.begin_nested():
            await _turno(db_session, base)


async def test_sobreturno_queda_fuera_del_exclude(db_session: AsyncSession) -> None:
    base = await _base(db_session)
    await _turno(db_session, base)
    await _turno(db_session, base, is_overbooking=True, overbooking_reason="Urgencia ficticia")


async def test_otra_clinica_no_colisiona(db_session: AsyncSession) -> None:
    base = await _base(db_session)
    otra = await _base(db_session)
    await _turno(db_session, base)
    await _turno(db_session, otra)


# ------------------------------------------------------------------- CHECKs


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"minutes": 0}, "ck_appointment_range_order"),
        ({"buffer_min": -5}, "ck_appointment_occupied_after_end"),
        ({"is_overbooking": True}, "ck_appointment_overbooking_reason_coherent"),
        ({"overbooking_reason": "Sin sobreturno"}, "ck_appointment_overbooking_reason_coherent"),
        (
            {
                "origin": AppointmentOrigin.ONLINE,
                "status": AppointmentStatus.PENDING,
                "is_overbooking": True,
                "overbooking_reason": "Online ficticio",
            },
            "ck_appointment_online_not_overbooking",
        ),
        ({"status": AppointmentStatus.CANCELLED}, "ck_appointment_cancellation_coherent"),
        (
            {"cancelled_at": T10, "cancellation_reason": CancellationReason.OTRO},
            "ck_appointment_cancellation_coherent",
        ),
        (
            {
                "status": AppointmentStatus.CANCELLED,
                "cancelled_at": T10,
            },
            "ck_appointment_cancellation_coherent",
        ),
        ({"cancellation_note": "Nota sin cancelar"}, "ck_appointment_cancellation_note_coherent"),
        ({"notes": "x" * 501}, "ck_appointment_notes_length"),
        ({"created_by_user_id": None}, "ck_appointment_reception_has_creator"),
    ],
)
async def test_checks_de_coherencia(
    db_session: AsyncSession, overrides: dict[str, Any], constraint: str
) -> None:
    base = await _base(db_session)
    with pytest.raises(IntegrityError, match=constraint):
        async with db_session.begin_nested():
            await _turno(db_session, base, **overrides)


async def test_turno_online_pendiente_sin_creador_es_valido(db_session: AsyncSession) -> None:
    base = await _base(db_session)
    await _turno(
        db_session, base, origin=AppointmentOrigin.ONLINE, status=AppointmentStatus.PENDING
    )


async def test_cancelado_coherente_es_valido(db_session: AsyncSession) -> None:
    base = await _base(db_session)
    await _turno(
        db_session,
        base,
        status=AppointmentStatus.CANCELLED,
        cancelled_at=T10 - timedelta(hours=2),
        cancellation_reason=CancellationReason.CLINICA,
        cancellation_note="Nota ficticia",
    )


# --------------------------------------------------------- FKs intra-tenant


@pytest.mark.parametrize("ajeno", ["patient", "professional", "chair"])
async def test_referencias_de_otra_clinica_violan_la_fk_compuesta(
    db_session: AsyncSession, ajeno: str
) -> None:
    base = await _base(db_session)
    otra = await _base(db_session)
    with pytest.raises(IntegrityError, match=f"fk_appointment_clinic_id_{ajeno}_id_{ajeno}"):
        async with db_session.begin_nested():
            await make_appointment(
                db_session,
                base["clinic"],
                patient=otra["patient"] if ajeno == "patient" else base["patient"],
                professional=(
                    otra["professional"] if ajeno == "professional" else base["professional"]
                ),
                chair=otra["chair"] if ajeno == "chair" else base["chair"],
                starts_at=T10,
            )
