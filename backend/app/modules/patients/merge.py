"""Fusión asistida de pacientes duplicados (C-06, D9, Flujo 4 caso de error).

Una transacción: lock `FOR UPDATE` de ambos pacientes (por id) → validación →
completar contactos vacíos del conservado → reasignar los turnos del duplicado
(todos los estados) con un evento `updated` por turno → archivar el duplicado
con su puntero → registro append-only en `patient_merge`. Nunca se borra nada
(regla 7) y la auditoría no guarda nombre, teléfono ni email (regla 13).

Contrato para C-09/C-12: los jobs de recordatorio y la lista de espera del
duplicado deben reasignarse o cancelarse en esta misma transacción.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import DomainError
from app.common.principal import Principal
from app.models import (
    ActorType,
    Appointment,
    AppointmentEvent,
    AppointmentEventType,
    Patient,
    PatientMerge,
)
from app.modules.appointments.audit import slot_snapshot
from app.modules.patients.schemas import PatientMergeRequest, PatientMergeResult

# Contacto que el conservado hereda si lo tiene vacío. `whatsapp_opt_in` no: el
# consentimiento es de quien lo dio para ese contacto.
_FILLABLE = ("phone_e164", "email", "dni")


async def merge_patients(
    session: AsyncSession,
    principal: Principal,
    source_id: uuid.UUID,
    payload: PatientMergeRequest,
    now: datetime,
) -> PatientMergeResult:
    target_id = payload.into_patient_id
    if source_id == target_id:
        raise DomainError(422, "invalid_merge")
    filas = (
        (
            await session.execute(
                select(Patient)
                .where(
                    Patient.clinic_id == principal.clinic_id, Patient.id.in_([source_id, target_id])
                )
                .order_by(Patient.id)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    por_id = {p.id: p for p in filas}
    source, target = por_id.get(source_id), por_id.get(target_id)
    # Ajeno, inexistente, archivado o ya fusionado: misma respuesta (no revela existencia).
    if source is None or target is None or source.archived_at or target.archived_at:
        raise DomainError(422, "invalid_merge")

    completados = [c for c in _FILLABLE if getattr(target, c) is None and getattr(source, c)]
    for campo in completados:
        setattr(target, campo, getattr(source, campo))

    turnos = (
        (
            await session.execute(
                select(Appointment)
                .where(
                    Appointment.clinic_id == principal.clinic_id,
                    Appointment.patient_id == source_id,
                )
                .order_by(Appointment.starts_at, Appointment.id)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    turno_ids = [str(t.id) for t in turnos]
    registro = PatientMerge(
        clinic_id=principal.clinic_id,
        source_patient_id=source_id,
        target_patient_id=target_id,
        actor_user_id=principal.user_id,
        appointment_ids=turno_ids,
        filled_fields=completados,
    )
    session.add(registro)
    source.archived_at = now
    source.merged_into_patient_id = target_id
    await session.flush()

    for turno in turnos:
        turno.patient_id = target_id
    session.add_all(
        [
            AppointmentEvent(
                clinic_id=principal.clinic_id,
                appointment_id=turno.id,
                actor_type=ActorType.USER,
                actor_user_id=principal.user_id,
                event=AppointmentEventType.UPDATED,
                from_status=turno.status,
                to_status=turno.status,
                payload={
                    "patient_id": [str(source_id), str(target_id)],
                    "reason": "patient_merge",
                    "merge_id": str(registro.id),
                },
                **slot_snapshot(turno),
            )
            for turno in turnos
        ]
    )
    await session.flush()
    await session.commit()
    return PatientMergeResult(
        merge_id=registro.id,
        source_patient_id=source_id,
        target_patient_id=target_id,
        moved_appointments=len(turnos),
        appointment_ids=[uuid.UUID(t) for t in turno_ids],
        filled_fields=completados,
    )
