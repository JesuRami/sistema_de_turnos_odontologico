"""Transiciones de estado de los `reminder_job` con su `delivery_event` (C-09, D1/D4).

Un solo lugar escribe el cierre de un job pendiente (`cancelled`, `skipped`, `failed`) y su
evento, así la programación, el consentimiento y el despacho no divergen. Todo corre en la
transacción del llamador (sin commit) y filtra siempre por `clinic_id` (regla 4). El payload del
evento lleva solo códigos, nunca nombre, teléfono, email ni link (regla 13).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import ColumnElement, insert, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    DeliveryEvent,
    DeliveryEventType,
    ReminderJob,
    ReminderReason,
    ReminderStatus,
)

_EVENT_FOR_STATUS = {
    ReminderStatus.CANCELLED: DeliveryEventType.CANCELLED,
    ReminderStatus.SKIPPED: DeliveryEventType.SKIPPED,
    ReminderStatus.FAILED: DeliveryEventType.FAILED,
}


def add_event(
    session: AsyncSession,
    job_id: uuid.UUID,
    clinic_id: uuid.UUID,
    event_type: DeliveryEventType,
    payload: dict[str, Any] | None = None,
    *,
    provider_event_id: str | None = None,
) -> DeliveryEvent:
    """Agrega un evento a la sesión (el `flush` lo hace el llamador)."""
    evento = DeliveryEvent(
        clinic_id=clinic_id,
        reminder_job_id=job_id,
        event_type=event_type,
        provider_event_id=provider_event_id,
        payload=payload or {},
    )
    session.add(evento)
    return evento


async def close_scheduled(
    session: AsyncSession,
    conditions: Sequence[ColumnElement[bool]],
    *,
    to: ReminderStatus,
    reason: ReminderReason,
) -> list[uuid.UUID]:
    """Pasa a `to` los jobs `scheduled` que cumplen `conditions` y registra un evento por job.

    Solo toca jobs `scheduled`: uno `sending`, `sent` o ya cerrado no se pisa. Devuelve los ids
    afectados. La sesión no se sincroniza: los objetos ya cargados quedan viejos hasta releerlos.
    """
    if to not in _EVENT_FOR_STATUS:
        raise ValueError(f"estado de cierre inválido: {to}")
    filas = await session.execute(
        update(ReminderJob)
        .where(ReminderJob.status == ReminderStatus.SCHEDULED, *conditions)
        .values(status=to, reason=reason.value)
        .returning(ReminderJob.id, ReminderJob.clinic_id)
        .execution_options(synchronize_session=False)
    )
    cerrados = filas.all()
    if cerrados:
        # Un solo INSERT multi-fila: es el camino de cancelación, el más caliente del motor.
        await session.execute(
            insert(DeliveryEvent).values(
                [
                    {
                        "clinic_id": clinic_id,
                        "reminder_job_id": job_id,
                        "event_type": _EVENT_FOR_STATUS[to],
                        "payload": {"reason": reason.value},
                    }
                    for job_id, clinic_id in cerrados
                ]
            )
        )
    return [job_id for job_id, _ in cerrados]
