"""Auditoría y cierres compartidos de la lista de espera (C-12, D9; RN-GL-01, regla 13).

`record_event` agrega el evento a la transacción del llamador y hace `flush`: si la base lo
rechaza, la operación entera falla. El payload lleva ids, horarios, códigos y motivos operativos;
nunca nombre, teléfono, email ni notas del paciente.

`close_pending_offer` es el único cierre de una oferta sin respuesta del paciente (`cancelled`):
cierra también sus envíos pendientes en el motor.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ReminderJob,
    ReminderReason,
    ReminderStatus,
    WaitlistEvent,
    WaitlistEventType,
    WaitlistOffer,
    WaitlistOfferStatus,
)
from app.modules.agenda.audit import to_json
from app.modules.appointments.audit import Actor
from app.modules.reminders.jobs import close_scheduled


async def record_event(
    session: AsyncSession,
    actor: Actor,
    *,
    clinic_id: uuid.UUID,
    entry_id: uuid.UUID,
    event: WaitlistEventType,
    offer_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    session.add(
        WaitlistEvent(
            clinic_id=clinic_id,
            entry_id=entry_id,
            offer_id=offer_id,
            event=event,
            actor_type=actor.type,
            actor_user_id=actor.user_id,
            payload=to_json(payload or {}),
        )
    )
    await session.flush()


def offer_payload(offer: WaitlistOffer) -> dict[str, Any]:
    """Hueco de la oferta para los eventos y el reporte (solo ids y horarios)."""
    return {
        "professional_id": offer.professional_id,
        "chair_id": offer.chair_id,
        "starts_at": offer.starts_at,
        "ends_at": offer.ends_at,
        "mode": offer.mode,
    }


async def close_offer_jobs(session: AsyncSession, offer: WaitlistOffer) -> None:
    """Los envíos todavía `scheduled` de la oferta quedan `cancelled` (`offer_closed`)."""
    await close_scheduled(
        session,
        [ReminderJob.clinic_id == offer.clinic_id, ReminderJob.waitlist_offer_id == offer.id],
        to=ReminderStatus.CANCELLED,
        reason=ReminderReason.OFFER_CLOSED,
    )


async def finish_offer(
    session: AsyncSession,
    actor: Actor,
    offer: WaitlistOffer,
    *,
    status: WaitlistOfferStatus,
    event: WaitlistEventType,
    now: datetime,
    reason: str | None = None,
    responded: bool = False,
    extra: dict[str, Any] | None = None,
) -> None:
    """Cierra una oferta `pending` (sin tocar la entrada) con su evento y sus envíos."""
    offer.status = status
    offer.closed_reason = reason
    if responded:
        offer.responded_at = now
    await session.flush()
    await close_offer_jobs(session, offer)
    await record_event(
        session,
        actor,
        clinic_id=offer.clinic_id,
        entry_id=offer.entry_id,
        event=event,
        offer_id=offer.id,
        payload={**offer_payload(offer), **({"reason": reason} if reason else {}), **(extra or {})},
    )


async def close_pending_offer(
    session: AsyncSession,
    actor: Actor,
    offer: WaitlistOffer,
    *,
    reason: str,
    now: datetime,
) -> None:
    """Oferta cerrada sin respuesta del paciente: `cancelled` con su motivo."""
    await finish_offer(
        session,
        actor,
        offer,
        status=WaitlistOfferStatus.CANCELLED,
        event=WaitlistEventType.OFFER_CANCELLED,
        now=now,
        reason=reason,
    )
