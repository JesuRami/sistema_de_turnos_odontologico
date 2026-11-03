"""Servicio del dominio clinic: consultas de recursos siempre acotadas a la clínica.

Reglas: `clinic_id` obligatorio en todo filtro (regla 4), columnas explícitas
(sin SELECT *, regla 8) y sin borrado físico (regla 7). Las políticas (C-04)
se editan solo sobre la clínica del principal y cada cambio se audita.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import DomainError
from app.common.phone import InvalidPhoneError, normalize_phone_e164
from app.common.principal import Principal
from app.models import (
    Chair,
    Clinic,
    ConfigAction,
    ConfigEntity,
    Patient,
    Professional,
    ScheduleRule,
)
from app.modules.agenda.audit import apply_changes, record_config_event
from app.modules.clinic.schemas import ClinicPolicies, ClinicPoliciesUpdate


class PoliciesService:
    """Lectura y edición de las políticas de la clínica del principal (US-004).

    Contrato para C-09 (US-004 CA-2): el `reminder_job` copia el paso al
    programarse; cambiar `reminder_steps` acá nunca toca jobs ya programados.
    """

    def __init__(self, session: AsyncSession, principal: Principal) -> None:
        self.session = session
        self.principal = principal

    async def _clinic(self) -> Clinic:
        clinic = (
            await self.session.execute(select(Clinic).where(Clinic.id == self.principal.clinic_id))
        ).scalar_one()
        return clinic

    @staticmethod
    def _read(clinic: Clinic) -> ClinicPolicies:
        return ClinicPolicies.model_validate(
            {
                "cancellation_window_hours": clinic.cancellation_window_hours,
                "reminder_steps": clinic.reminder_steps,
                "max_overbookings_per_day": clinic.max_overbookings_per_day,
                "waitlist_offer_ttl_hours": clinic.waitlist_offer_ttl_hours,
            }
        )

    async def get(self) -> ClinicPolicies:
        return self._read(await self._clinic())

    async def update(self, payload: ClinicPoliciesUpdate) -> ClinicPolicies:
        clinic = await self._clinic()
        cambios = apply_changes(clinic, payload.model_dump(include=payload.model_fields_set))
        if cambios:
            await self.session.flush()
            record_config_event(
                self.session,
                self.principal,
                entity=ConfigEntity.CLINIC_POLICY,
                entity_id=clinic.id,
                action=ConfigAction.UPDATED,
                changes=cambios,
            )
            await self.session.commit()
            await self.session.refresh(clinic)
        return self._read(clinic)


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
