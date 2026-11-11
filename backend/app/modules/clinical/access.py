"""Control de acceso clínico (C-15, D4). Única puerta para todo endpoint clínico.

- `ClinicalReader`: `admin` u `odontologo` (envuelve `require_roles`, sin duplicar su lógica).
  Recepción → `403 forbidden_role` antes de que corra el handler (no escribe filas ni eventos).
- `ClinicalWriter`: lo anterior **y** `professional_id` en el principal; si no,
  `403 professional_required` (admin que no atiende: lee pero no escribe, Decisión 1).
- `ClinicalAdmin`: solo admin (bitácora de accesos, adjuntos dados de baja).
- `resolve_patient` / `resolve_record`: cargan por `(id, clinic_id)` del principal y, para un
  odontólogo, exigen al menos un turno suyo con el paciente (Decisión 2). Fuera de alcance,
  de otra clínica o inexistente → `404 patient_not_found`, indistinguibles.

Las escrituras toman `FOR SHARE` sobre el `patient` (la fusión de C-06 toma `FOR UPDATE`): o la
fusión bloquea la escritura (`409 patient_archived`) o la escritura bloquea la fusión.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy import Select, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import require_roles
from app.common.exceptions import DomainError
from app.common.principal import Principal
from app.models import Appointment, ClinicalRecord, Patient, UserRole

_reader = require_roles(UserRole.ADMIN, UserRole.ODONTOLOGO)
_admin = require_roles(UserRole.ADMIN)


async def require_clinical_writer(principal: Annotated[Principal, Depends(_reader)]) -> Principal:
    """Escribir exige identidad profesional: la autoría sale del principal, nunca del cuerpo."""
    if principal.professional_id is None:
        raise DomainError(403, "professional_required")
    return principal


ClinicalReader = Annotated[Principal, Depends(_reader)]
ClinicalWriter = Annotated[Principal, Depends(require_clinical_writer)]
ClinicalAdmin = Annotated[Principal, Depends(_admin)]


def is_admin(principal: Principal) -> bool:
    return UserRole.ADMIN in principal.roles


def _is_dentist_only(principal: Principal) -> bool:
    return principal.roles == {UserRole.ODONTOLOGO}


@dataclass(frozen=True, slots=True)
class PatientRef:
    id: uuid.UUID
    full_name: str
    archived: bool


@dataclass(frozen=True, slots=True)
class RecordRef:
    id: uuid.UUID
    clinic_id: uuid.UUID
    patient_id: uuid.UUID
    patient_archived: bool


def _scoped(stmt: Select[Any], principal: Principal) -> Select[Any]:
    """Acota a la clínica y, para el odontólogo, a pacientes con un turno suyo (en SQL)."""
    stmt = stmt.where(Patient.clinic_id == principal.clinic_id)
    if _is_dentist_only(principal):
        stmt = stmt.where(
            exists().where(
                Appointment.clinic_id == Patient.clinic_id,
                Appointment.patient_id == Patient.id,
                Appointment.professional_id == principal.professional_id,
            )
        )
    return stmt


def _not_found() -> DomainError:
    return DomainError(404, "patient_not_found")


async def resolve_patient(
    session: AsyncSession, principal: Principal, patient_id: uuid.UUID, *, write: bool = False
) -> PatientRef:
    """Paciente en alcance; `write=True` toma `FOR SHARE` y rechaza archivados (`409`)."""
    stmt = _scoped(
        select(Patient.id, Patient.full_name, Patient.archived_at).where(Patient.id == patient_id),
        principal,
    )
    if write:
        stmt = stmt.with_for_update(read=True, of=Patient)
    fila = (await session.execute(stmt)).one_or_none()
    if fila is None:
        raise _not_found()
    if write and fila.archived_at is not None:
        raise DomainError(409, "patient_archived")
    return PatientRef(
        id=fila.id, full_name=str(fila.full_name), archived=fila.archived_at is not None
    )


async def resolve_record(
    session: AsyncSession, principal: Principal, record_id: uuid.UUID, *, write: bool = False
) -> RecordRef:
    """Ficha en alcance por su id; misma semántica de `404`/`409` que `resolve_patient`."""
    stmt = _scoped(
        select(ClinicalRecord.id, ClinicalRecord.patient_id, Patient.archived_at)
        .join(
            Patient,
            (Patient.clinic_id == ClinicalRecord.clinic_id)
            & (Patient.id == ClinicalRecord.patient_id),
        )
        .where(ClinicalRecord.id == record_id, ClinicalRecord.clinic_id == principal.clinic_id),
        principal,
    )
    if write:
        stmt = stmt.with_for_update(read=True, of=Patient)
    fila = (await session.execute(stmt)).one_or_none()
    if fila is None:
        raise _not_found()
    if write and fila.archived_at is not None:
        raise DomainError(409, "patient_archived")
    return RecordRef(
        id=fila.id,
        clinic_id=principal.clinic_id,
        patient_id=fila.patient_id,
        patient_archived=fila.archived_at is not None,
    )
