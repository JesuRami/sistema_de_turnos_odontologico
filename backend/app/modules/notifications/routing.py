"""Enrutamiento de una respuesta del paciente a clínica, ficha y turno (C-10, D7).

1. **Contexto**: si el paciente cita un mensaje, el `context.id` es el `provider_message_id` de un
   job; vale solo si la ficha del turno tiene el teléfono del remitente y su clínica usa el número
   que recibió el mensaje. `routed_by = context`.
2. **Teléfono**: si no, las clínicas candidatas son la dueña del número receptor (número propio) o
   todas las que usan el compartido; las fichas candidatas, las no fusionadas con ese teléfono.
   Para confirmar o cambiar se exige UN único turno `pending|confirmed` futuro entre ellas; con
   cero o varios, el resultado es ambiguo y no se toca ningún turno. `routed_by = phone`.

Nunca se adivina: un remitente o número desconocido no produce destinos. Toda consulta filtra
por las clínicas candidatas (regla 4). Ningún teléfono sale de este módulo hacia un log.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import and_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import Settings
from app.models import (
    Appointment,
    AppointmentStatus,
    Clinic,
    Patient,
    ReminderJob,
    WaitingListEntry,
    WaitlistOffer,
    WhatsAppIntent,
)

_OPERABLES = (AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED)


@dataclass(frozen=True, slots=True)
class Target:
    """Un destino del entrante: clínica, ficha y (si se resolvió) turno."""

    clinic_id: uuid.UUID
    patient_id: uuid.UUID
    appointment_id: uuid.UUID | None = None
    # C-12 (D8): el paciente citó el mensaje de una oferta de la lista de espera.
    waitlist_offer_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class Routing:
    routed_by: str
    targets: list[Target] = field(default_factory=list)
    # Se buscaba un turno y no hubo exactamente uno.
    ambiguous: bool = False


def sender_forms(wa_id: str) -> list[str]:
    """E.164 posibles del remitente. Argentina: Meta puede entregar el móvil con o sin el `9`."""
    formas = ["+" + wa_id]
    if wa_id.startswith("549"):
        formas.append("+54" + wa_id[3:])
    elif wa_id.startswith("54"):
        formas.append("+549" + wa_id[2:])
    return formas


async def candidate_clinics(
    session: AsyncSession, settings: Settings, phone_number_id: str
) -> list[uuid.UUID]:
    propia = await session.scalar(
        select(Clinic.id).where(Clinic.whatsapp_phone_number_id == phone_number_id)
    )
    if propia is not None:
        return [propia]
    if phone_number_id != settings.META_PHONE_NUMBER_ID.strip():
        return []
    return list(
        (
            await session.execute(
                select(Clinic.id)
                .where(Clinic.whatsapp_phone_number_id.is_(None))
                .order_by(Clinic.id)
            )
        )
        .scalars()
        .all()
    )


async def _by_context(
    session: AsyncSession, context_id: str, formas: list[str], clinicas: list[uuid.UUID]
) -> Target | None:
    fila = (
        await session.execute(
            select(Appointment.clinic_id, Appointment.patient_id, Appointment.id)
            .select_from(ReminderJob)
            .join(
                Appointment,
                and_(
                    Appointment.clinic_id == ReminderJob.clinic_id,
                    Appointment.id == ReminderJob.appointment_id,
                ),
            )
            .join(
                Patient,
                and_(
                    Patient.clinic_id == Appointment.clinic_id, Patient.id == Appointment.patient_id
                ),
            )
            .where(
                ReminderJob.provider_message_id == context_id,
                ReminderJob.clinic_id.in_(clinicas),
                Patient.phone_e164.in_(formas),
                Patient.merged_into_patient_id.is_(None),
            )
        )
    ).one_or_none()
    if fila is None:
        return None
    return Target(clinic_id=fila.clinic_id, patient_id=fila.patient_id, appointment_id=fila.id)


async def _by_offer_context(
    session: AsyncSession, context_id: str, formas: list[str], clinicas: list[uuid.UUID]
) -> Target | None:
    """El mensaje citado es el envío de una oferta (C-12): oferta → entrada → paciente."""
    fila = (
        await session.execute(
            select(WaitlistOffer.clinic_id, WaitingListEntry.patient_id, WaitlistOffer.id)
            .select_from(ReminderJob)
            .join(
                WaitlistOffer,
                and_(
                    WaitlistOffer.clinic_id == ReminderJob.clinic_id,
                    WaitlistOffer.id == ReminderJob.waitlist_offer_id,
                ),
            )
            .join(
                WaitingListEntry,
                and_(
                    WaitingListEntry.clinic_id == WaitlistOffer.clinic_id,
                    WaitingListEntry.id == WaitlistOffer.entry_id,
                ),
            )
            .join(
                Patient,
                and_(
                    Patient.clinic_id == WaitingListEntry.clinic_id,
                    Patient.id == WaitingListEntry.patient_id,
                ),
            )
            .where(
                ReminderJob.provider_message_id == context_id,
                ReminderJob.clinic_id.in_(clinicas),
                Patient.phone_e164.in_(formas),
                Patient.merged_into_patient_id.is_(None),
            )
        )
    ).one_or_none()
    if fila is None:
        return None
    return Target(clinic_id=fila[0], patient_id=fila[1], waitlist_offer_id=fila[2])


async def route(
    session: AsyncSession,
    settings: Settings,
    *,
    phone_number_id: str,
    wa_id: str,
    context_id: str | None,
    intent: WhatsAppIntent,
    now: datetime,
) -> Routing:
    clinicas = await candidate_clinics(session, settings, phone_number_id)
    if not clinicas:
        return Routing(routed_by="phone")
    formas = sender_forms(wa_id)
    if context_id:
        destino = await _by_context(session, context_id, formas, clinicas)
        if destino is None:
            destino = await _by_offer_context(session, context_id, formas, clinicas)
        if destino is not None:
            return Routing(routed_by="context", targets=[destino])
    fichas = (
        await session.execute(
            select(Patient.clinic_id, Patient.id)
            .where(
                Patient.clinic_id.in_(clinicas),
                Patient.phone_e164.in_(formas),
                Patient.merged_into_patient_id.is_(None),
            )
            .order_by(Patient.clinic_id, Patient.id)
        )
    ).all()
    if not fichas:
        return Routing(routed_by="phone")
    if intent is WhatsAppIntent.STOP:
        return Routing(
            routed_by="phone", targets=[Target(clinic_id=c, patient_id=p) for c, p in fichas]
        )
    turnos = (
        await session.execute(
            select(Appointment.clinic_id, Appointment.patient_id, Appointment.id)
            .where(
                tuple_(Appointment.clinic_id, Appointment.patient_id).in_(
                    [(c, p) for c, p in fichas]
                ),
                Appointment.status.in_(_OPERABLES),
                Appointment.starts_at > now,
            )
            .limit(2)
        )
    ).all()
    if len(turnos) == 1:
        [(clinica, paciente, turno)] = turnos
        return Routing(
            routed_by="phone",
            targets=[Target(clinic_id=clinica, patient_id=paciente, appointment_id=turno)],
        )
    # Ambiguo (o sin turno): una ficha por clínica candidata, sin turno.
    por_clinica: dict[uuid.UUID, uuid.UUID] = {}
    for clinica, paciente in fichas:
        por_clinica.setdefault(clinica, paciente)
    return Routing(
        routed_by="phone",
        targets=[Target(clinic_id=c, patient_id=p) for c, p in por_clinica.items()],
        ambiguous=intent in (WhatsAppIntent.CONFIRM, WhatsAppIntent.CHANGE),
    )
