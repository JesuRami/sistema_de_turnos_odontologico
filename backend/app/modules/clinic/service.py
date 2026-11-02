"""Servicio del dominio clinic: consultas de recursos siempre acotadas a la clínica.

Reglas: `clinic_id` obligatorio en todo filtro (regla 4), columnas explícitas
(sin SELECT *, regla 8) y sin borrado físico (regla 7).
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import DomainError
from app.common.phone import InvalidPhoneError, normalize_phone_e164
from app.models import Chair, Patient, Professional, ScheduleRule


class ClinicService:
    """Stub de servicio (los routers delegan aquí, nunca lógica inline)."""

    async def ping(self) -> str:
        """Verifica cableado router→servicio."""
        return "ok"


async def list_active_professionals(
    session: AsyncSession, clinic_id: uuid.UUID
) -> Sequence[Professional]:
    """Profesionales activos de la clínica, ordenados por nombre."""
    stmt = (
        select(Professional)
        .where(Professional.clinic_id == clinic_id, Professional.active.is_(True))
        .order_by(Professional.display_name, Professional.id)
    )
    return (await session.execute(stmt)).scalars().all()


async def list_active_chairs(session: AsyncSession, clinic_id: uuid.UUID) -> Sequence[Chair]:
    """Sillones activos de la clínica, ordenados por nombre."""
    stmt = (
        select(Chair)
        .where(Chair.clinic_id == clinic_id, Chair.active.is_(True))
        .order_by(Chair.name, Chair.id)
    )
    return (await session.execute(stmt)).scalars().all()


async def list_schedule_rules(
    session: AsyncSession, clinic_id: uuid.UUID, professional_id: uuid.UUID
) -> Sequence[ScheduleRule]:
    """Reglas semanales del profesional dentro de la clínica (día y hora ascendentes)."""
    stmt = (
        select(ScheduleRule)
        .where(
            ScheduleRule.clinic_id == clinic_id,
            ScheduleRule.professional_id == professional_id,
        )
        .order_by(ScheduleRule.weekday, ScheduleRule.start_time, ScheduleRule.id)
    )
    return (await session.execute(stmt)).scalars().all()


async def find_patients_by_phone(
    session: AsyncSession, clinic_id: uuid.UUID, raw_phone: str
) -> Sequence[Patient]:
    """Pacientes activos de la clínica con ese teléfono (E.164), el más reciente primero.

    Los pacientes archivados (baja lógica) quedan excluidos.
    Un teléfono puede ser compartido (familias): devuelve todos los coincidentes.
    Lanza `InvalidPhoneError` (sin el valor) si la entrada no es un teléfono válido.
    """
    phone = normalize_phone_e164(raw_phone)
    stmt = (
        select(Patient)
        .where(
            Patient.clinic_id == clinic_id,
            Patient.phone_e164 == phone,
            Patient.archived_at.is_(None),
        )
        .order_by(Patient.created_at.desc(), Patient.id)
    )
    return (await session.execute(stmt)).scalars().all()


# Mensajes públicos genéricos: jamás incluyen nombre, teléfono ni email (regla 13).
# El DETAIL de Postgres (`Failing row contains ...`) trae la fila completa, por eso
# la IntegrityError se descarta y no se encadena.
_INVALID_PATIENT = "Datos de paciente inválidos"
_INVALID_PHONE = "Teléfono inválido"


async def persist_patient(session: AsyncSession, patient: Patient) -> Patient:
    """Inserta el paciente en un savepoint; ante violación de constraint, error de dominio 422."""
    try:
        async with session.begin_nested():
            session.add(patient)
            await session.flush()
    except IntegrityError:
        raise DomainError(422, _INVALID_PATIENT) from None
    return patient


async def create_patient(
    session: AsyncSession,
    clinic_id: uuid.UUID,
    *,
    full_name: str,
    phone: str | None = None,
    email: str | None = None,
    dni: str | None = None,
    whatsapp_opt_in: bool = False,
) -> Patient:
    """Crea un paciente normalizando el teléfono a E.164 (región AR por defecto)."""
    try:
        phone_e164 = normalize_phone_e164(phone) if phone else None
    except InvalidPhoneError:
        raise DomainError(422, _INVALID_PHONE) from None
    patient = Patient(
        clinic_id=clinic_id,
        full_name=full_name,
        phone_e164=phone_e164,
        email=email,
        dni=dni,
        whatsapp_opt_in=whatsapp_opt_in,
    )
    return await persist_patient(session, patient)
