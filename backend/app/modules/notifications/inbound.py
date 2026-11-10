"""Mensaje entrante del paciente: registro, acción y respuesta encolada (C-10, D7; RN-WA-01/03).

Orden dentro de la transacción del evento:

1. Clasifica la intención y enruta (contexto → teléfono). Sin destinos: no se persiste nada del
   remitente y se cuenta `whatsapp_inbound_unrouted`.
2. Inserta una fila `whatsapp_inbound` por clínica destino con `ON CONFLICT DO NOTHING`: si
   ninguna se insertó, el mensaje ya se procesó (reenvío de Meta) y no se repite nada.
3. Aplica la acción:

   | intención | resultado | efecto | respuesta |
   |---|---|---|---|
   | confirm | turno `pending` futuro | `confirm_by_patient` (fuente `whatsapp`) | `confirmed` |
   | confirm | turno `confirmed` futuro | no-op auditado | `confirmed` |
   | confirm/change | turno no operable o iniciado | nada | `inactive` |
   | change | ventana de cancelación abierta | nada | `change_link` |
   | change | ventana cerrada | nada | `change_contact` |
   | confirm/change | 0 o varios turnos | nada | `ambiguous` |
   | stop | ≥ 1 ficha | opt-out `whatsapp_reply` por ficha | `stop_ack` si alguna cambió |
   | unknown | — | solo registro | ninguna |
   | aceptar oferta (C-12) | oferta citada, vigente | turno `waitlist` | `offer_accepted` |
   | rechazar oferta (C-12) | oferta citada, vigente | rechazo y rotación | `offer_declined` |
   | aceptar oferta (C-12) | vencida, cerrada, ocupada u otro turno | nada | ver D8 |

   Aceptar: botón "Tomarlo", "tomarlo" o "sí" citando la oferta; rechazar: botón "Paso", "paso" o
   "no" citando la oferta. Sin citar la oferta, "tomarlo"/"paso" no hacen nada.

   "NO" nunca cancela (decisión aprobada 2026-11-06). Con varias clínicas, la respuesta única se
   atribuye a la de menor id (determinista) y su texto no nombra ninguna.

Regla 13: no se guarda el texto ni el teléfono; los logs llevan solo códigos.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import DomainError
from app.core.settings import Settings
from app.models import (
    Appointment,
    AppointmentStatus,
    Clinic,
    ConsentSource,
    ConsentStatus,
    Patient,
    ReminderChannel,
    WhatsAppInbound,
    WhatsAppIntent,
    WhatsAppOutboundReply,
    WhatsAppReplyKind,
)
from app.modules.manage.actions import confirm_by_patient
from app.modules.notifications.intents import classify
from app.modules.notifications.payload import InboundMessage
from app.modules.notifications.routing import Routing, Target, route
from app.modules.notifications.statuses import meta_instant
from app.modules.reminders.consent import ConsentService

logger = logging.getLogger("notifications.inbound")

# RN-WA-03: el texto libre solo se admite dentro de las 24 h posteriores al mensaje del paciente.
SESSION_WINDOW = timedelta(hours=24)
_OPERABLES = (AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED)


async def apply_inbound(
    session: AsyncSession,
    settings: Settings,
    phone_number_id: str,
    message: InboundMessage,
    *,
    now: datetime,
) -> None:
    intent = classify(message)
    routing = await route(
        session,
        settings,
        phone_number_id=phone_number_id,
        wa_id=message.from_,
        context_id=message.context.id if message.context else None,
        intent=intent,
        now=now,
    )
    if not routing.targets:
        logger.info("whatsapp_inbound_unrouted intent=%s", intent.value)
        return
    occurred_at = meta_instant(message.timestamp)
    destinos = sorted(routing.targets, key=lambda t: t.clinic_id)
    insertados: dict[Target, object] = {}
    for destino in destinos:
        inbound_id = await session.scalar(
            pg_insert(WhatsAppInbound)
            .values(
                clinic_id=destino.clinic_id,
                provider_message_id=message.id,
                phone_number_id=phone_number_id,
                patient_id=destino.patient_id,
                appointment_id=destino.appointment_id,
                waitlist_offer_id=destino.waitlist_offer_id,
                intent=_effective_intent(intent, destino),
                routed_by=routing.routed_by,
                occurred_at=occurred_at,
            )
            .on_conflict_do_nothing(index_elements=["clinic_id", "provider_message_id"])
            .returning(WhatsAppInbound.id)
        )
        if inbound_id is not None:
            insertados[destino] = inbound_id
    if not insertados:
        return  # reenvío de Meta: ya procesado
    await _act(session, settings, intent, routing, insertados, occurred_at=occurred_at, now=now)


def _effective_intent(intent: WhatsAppIntent, destino: Target) -> WhatsAppIntent:
    """Citando una oferta, "sí" acepta y "no" rechaza (C-12, D8); sin oferta no cambia nada."""
    if destino.waitlist_offer_id is not None:
        if intent is WhatsAppIntent.CONFIRM:
            return WhatsAppIntent.ACCEPT_OFFER
        if intent is WhatsAppIntent.CHANGE:
            return WhatsAppIntent.DECLINE_OFFER
    return intent


async def _act(
    session: AsyncSession,
    settings: Settings,
    intent: WhatsAppIntent,
    routing: Routing,
    insertados: dict[Target, object],
    *,
    occurred_at: datetime,
    now: datetime,
) -> None:
    primero = next(iter(insertados))

    async def responder(kind: WhatsAppReplyKind, destino: Target = primero) -> None:
        await enqueue_reply(
            session,
            destino,
            # C-12: la respuesta a una oferta aceptada apunta al turno nuevo (otro `Target`).
            inbound_id=insertados.get(destino, insertados[primero]),
            kind=kind,
            occurred_at=occurred_at,
            now=now,
        )

    if intent is WhatsAppIntent.UNKNOWN:
        return
    if intent is WhatsAppIntent.STOP:
        cambio = False
        servicio = ConsentService(session)
        for destino in insertados:
            paciente = await session.get(Patient, destino.patient_id)
            if paciente is None or paciente.clinic_id != destino.clinic_id:
                continue
            cambio |= await servicio.record(
                paciente,
                ReminderChannel.WHATSAPP,
                ConsentStatus.OPT_OUT,
                ConsentSource.WHATSAPP_REPLY,
            )
        if cambio:
            await responder(WhatsAppReplyKind.STOP_ACK)
        return
    if primero.waitlist_offer_id is not None:
        await _offer_action(
            session, settings, _effective_intent(intent, primero), primero, responder, now=now
        )
        return
    if intent in (WhatsAppIntent.ACCEPT_OFFER, WhatsAppIntent.DECLINE_OFFER):
        # Sin citar una oferta, "tomarlo"/"paso" no hacen nada (spec: nunca acepta sin contexto).
        return
    if routing.ambiguous or primero.appointment_id is None:
        await responder(WhatsAppReplyKind.AMBIGUOUS)
        return
    await responder(await _appointment_action(session, intent, primero, now=now))


async def _appointment_action(
    session: AsyncSession, intent: WhatsAppIntent, destino: Target, *, now: datetime
) -> WhatsAppReplyKind:
    assert destino.appointment_id is not None
    fila = (
        await session.execute(
            select(
                Appointment.status,
                Appointment.starts_at,
                Clinic.timezone,
                Clinic.cancellation_window_hours,
            )
            .join(Clinic, Clinic.id == Appointment.clinic_id)
            .where(
                Appointment.clinic_id == destino.clinic_id,
                Appointment.id == destino.appointment_id,
            )
        )
    ).one()
    if fila.status not in _OPERABLES or now >= fila.starts_at:
        return WhatsAppReplyKind.INACTIVE
    if intent is WhatsAppIntent.CHANGE:
        cierre = fila.starts_at - timedelta(hours=fila.cancellation_window_hours)
        return WhatsAppReplyKind.CHANGE_LINK if now <= cierre else WhatsAppReplyKind.CHANGE_CONTACT
    try:
        async with session.begin_nested():
            await confirm_by_patient(
                session,
                clinic_id=destino.clinic_id,
                appointment_id=destino.appointment_id,
                now=now,
                tz=ZoneInfo(fila.timezone),
                cancellation_window_hours=fila.cancellation_window_hours,
                source="whatsapp",
            )
    except DomainError as error:
        logger.info("whatsapp_confirm_rejected code=%s", error.detail)
        return WhatsAppReplyKind.INACTIVE
    return WhatsAppReplyKind.CONFIRMED


_OFFER_ERRORS = {
    "slot_taken": WhatsAppReplyKind.OFFER_TAKEN,
    "offer_expired": WhatsAppReplyKind.OFFER_CLOSED,
    "offer_closed": WhatsAppReplyKind.OFFER_CLOSED,
    "patient_busy": WhatsAppReplyKind.OFFER_PATIENT_BUSY,
}


async def _offer_action(
    session: AsyncSession,
    settings: Settings,
    intent: WhatsAppIntent,
    destino: Target,
    responder: Callable[..., Awaitable[None]],
    *,
    now: datetime,
) -> None:
    """Aceptar o rechazar la oferta citada con el mismo servicio que el link (C-12, D8)."""
    from app.models import ActorType
    from app.modules.appointments.audit import Actor
    from app.modules.waiting_list.offers import OffersService

    if intent not in (WhatsAppIntent.ACCEPT_OFFER, WhatsAppIntent.DECLINE_OFFER):
        return
    assert destino.waitlist_offer_id is not None
    servicio = OffersService(
        session, Actor(clinic_id=destino.clinic_id, type=ActorType.PATIENT_TOKEN), now, settings
    )
    try:
        if intent is WhatsAppIntent.ACCEPT_OFFER:
            aceptada = await servicio.accept(destino.waitlist_offer_id, commit=False)
            turno = Target(
                clinic_id=destino.clinic_id,
                patient_id=destino.patient_id,
                appointment_id=aceptada.appointment_id,
                waitlist_offer_id=destino.waitlist_offer_id,
            )
            await responder(WhatsAppReplyKind.OFFER_ACCEPTED, turno)
            return
        await servicio.decline(destino.waitlist_offer_id, commit=False)
    except DomainError as error:
        logger.info("whatsapp_offer_rejected code=%s", error.detail)
        tipo = _OFFER_ERRORS.get(error.detail)
        if tipo is None:
            raise
        await responder(tipo)
        return
    await responder(WhatsAppReplyKind.OFFER_DECLINED)


async def enqueue_reply(
    session: AsyncSession,
    destino: Target,
    *,
    inbound_id: object,
    kind: WhatsAppReplyKind,
    occurred_at: datetime,
    now: datetime,
) -> None:
    """Respuesta al outbox; `UNIQUE (inbound_id, kind)` la hace idempotente."""
    await session.execute(
        pg_insert(WhatsAppOutboundReply)
        .values(
            clinic_id=destino.clinic_id,
            inbound_id=inbound_id,
            patient_id=destino.patient_id,
            appointment_id=destino.appointment_id,
            waitlist_offer_id=destino.waitlist_offer_id,
            kind=kind,
            available_at=now,
            expires_at=occurred_at + SESSION_WINDOW,
        )
        .on_conflict_do_nothing(index_elements=["inbound_id", "kind"])
    )
