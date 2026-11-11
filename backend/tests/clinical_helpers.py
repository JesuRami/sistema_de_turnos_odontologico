"""Escenario sintético de la historia clínica (C-15). Todo dato es ficticio (regla 13).

Una clínica con:
- `admin` (sin `professional_id`), `admin_prof` (admin que también atiende), `recepcion`,
  `odontologo` (profesional A) y `odontologo_b` (profesional B);
- `patient` con un turno del profesional A y `patient_b` con un turno solo del profesional B.

`headers[rol]` lleva un access válido por rol. `other` es una segunda clínica completa para las
pruebas cross-tenant.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from app.core.settings import Settings
from app.models import (
    Appointment,
    Chair,
    Clinic,
    ClinicalAccessEvent,
    ClinicalAction,
    Patient,
    Professional,
    User,
    UserRole,
)
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.auth_helpers import issue_session
from tests.factories import (
    make_appointment,
    make_chair,
    make_clinic,
    make_patient,
    make_professional,
    make_user,
    unique_email,
)

INICIO = datetime(2030, 1, 7, 13, 0, tzinfo=UTC)
NOMBRE_PACIENTE = "Paciente Prueba Ficticio"
DNI_FICTICIO = "99000111"
TEXTO_CLINICO = "Paciente Prueba Ficticio refiere dolor"


@dataclass(slots=True)
class ClinicScene:
    clinic: Clinic
    professional: Professional
    professional_b: Professional
    chair: Chair
    users: dict[str, User]
    patient: Patient
    patient_b: Patient
    appointment: Appointment
    appointment_b: Appointment
    headers: dict[str, dict[str, str]] = field(default_factory=dict)


async def make_clinic_scene(session: AsyncSession, redis: Redis, settings: Settings) -> ClinicScene:
    clinic = await make_clinic(session)
    prof_a = await make_professional(session, clinic, display_name="Dra. Ficticia A")
    prof_b = await make_professional(session, clinic, display_name="Dr. Ficticio B")
    chair = await make_chair(session, clinic)
    roles: dict[str, dict[str, Any]] = {
        "admin": {"role": UserRole.ADMIN},
        "admin_prof": {"role": UserRole.ADMIN, "professional_id": prof_a.id},
        "recepcion": {"role": UserRole.RECEPCION},
        "odontologo": {"role": UserRole.ODONTOLOGO, "professional_id": prof_a.id},
        "odontologo_b": {"role": UserRole.ODONTOLOGO, "professional_id": prof_b.id},
    }
    users = {
        nombre: await make_user(
            session,
            clinic,
            email=unique_email(f"{nombre}.ficticio"),
            must_change_password=False,
            **valores,
        )
        for nombre, valores in roles.items()
    }
    patient = await make_patient(session, clinic, full_name=NOMBRE_PACIENTE, dni=DNI_FICTICIO)
    patient_b = await make_patient(session, clinic, full_name="Paciente Ficticio Dos")
    turno = await make_appointment(
        session,
        clinic,
        patient=patient,
        professional=prof_a,
        chair=chair,
        starts_at=INICIO,
        created_by_user_id=users["admin"].id,
    )
    turno_b = await make_appointment(
        session,
        clinic,
        patient=patient_b,
        professional=prof_b,
        chair=chair,
        starts_at=INICIO.replace(hour=15),
        created_by_user_id=users["admin"].id,
    )
    headers = {
        nombre: (await issue_session(redis, settings, user)).headers
        for nombre, user in users.items()
    }
    return ClinicScene(
        clinic=clinic,
        professional=prof_a,
        professional_b=prof_b,
        chair=chair,
        users=users,
        patient=patient,
        patient_b=patient_b,
        appointment=turno,
        appointment_b=turno_b,
        headers=headers,
    )


async def seed_catalog(session: AsyncSession, clinic: Clinic) -> None:
    from app.modules.clinical.catalog import seed_clinical_catalog

    await seed_clinical_catalog(session, clinic.id)


async def open_record(
    client: httpx.AsyncClient, scene: ClinicScene, rol: str = "odontologo"
) -> uuid.UUID:
    respuesta = await client.post(
        f"/api/patients/{scene.patient.id}/clinical-record", headers=scene.headers[rol]
    )
    assert respuesta.status_code in (200, 201), respuesta.text
    return uuid.UUID(respuesta.json()["record_id"])


async def access_events(
    session: AsyncSession, *, action: ClinicalAction | None = None
) -> list[ClinicalAccessEvent]:
    stmt = select(ClinicalAccessEvent).order_by(
        ClinicalAccessEvent.created_at, ClinicalAccessEvent.id
    )
    if action is not None:
        stmt = stmt.where(ClinicalAccessEvent.action == action)
    return list(
        (await session.execute(stmt.execution_options(populate_existing=True))).scalars().all()
    )


async def count_rows(session: AsyncSession, model: Any) -> int:
    return int(await session.scalar(select(func.count()).select_from(model)) or 0)


def principal_of(user: User, role: UserRole | None = None) -> Any:
    """`Principal` de servicio (sin HTTP) para las carreras con commits reales."""
    from app.common.principal import Principal

    return Principal(
        user_id=user.id,
        clinic_id=user.clinic_id,
        email=user.email,
        roles=frozenset({role or user.role}),
        professional_id=user.professional_id,
        sid="sid-ficticio",
        must_change_password=False,
    )


@dataclass(slots=True)
class CommittedScene:
    """Escena mínima con commits reales: clínica, odontólogo con turno y paciente."""

    clinic_id: uuid.UUID
    dentist: User
    patient_id: uuid.UUID
    other_patient_id: uuid.UUID
    appointment_id: uuid.UUID


async def make_committed_scene(session: AsyncSession) -> CommittedScene:
    clinic = await make_clinic(session)
    prof = await make_professional(session, clinic)
    chair = await make_chair(session, clinic)
    admin = await make_user(session, clinic)
    dentist = await make_user(session, clinic, role=UserRole.ODONTOLOGO, professional_id=prof.id)
    patient = await make_patient(session, clinic, full_name=NOMBRE_PACIENTE)
    other = await make_patient(session, clinic, full_name="Paciente Ficticio Destino")
    turno = await make_appointment(
        session,
        clinic,
        patient=patient,
        professional=prof,
        chair=chair,
        starts_at=INICIO,
        created_by_user_id=admin.id,
    )
    await make_appointment(
        session,
        clinic,
        patient=other,
        professional=prof,
        chair=chair,
        starts_at=INICIO.replace(hour=16),
        created_by_user_id=admin.id,
    )
    from app.modules.clinical.catalog import seed_clinical_catalog

    await seed_clinical_catalog(session, clinic.id)
    await session.commit()
    return CommittedScene(clinic.id, dentist, patient.id, other.id, turno.id)
