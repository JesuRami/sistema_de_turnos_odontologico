"""Auditoría de turnos de toda la clínica (C-13, US-051 CA-2). Solo lectura, solo admin."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import paginate_entities
from app.models import AppointmentEvent, AppointmentEventType
from app.modules.reports.schemas import AuditEventRead, AuditPage


async def list_audit(
    session: AsyncSession,
    clinic_id: uuid.UUID,
    *,
    appointment_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    event: AppointmentEventType | None,
    desde: datetime | None,
    hasta: datetime | None,
    cursor: str | None,
    limit: int,
) -> AuditPage:
    """Eventos de la clínica por `(created_at, id)`; el filtro `clinic_id` sale del principal."""
    ev = AppointmentEvent
    stmt = select(ev).where(ev.clinic_id == clinic_id)
    if appointment_id is not None:
        stmt = stmt.where(ev.appointment_id == appointment_id)
    if actor_user_id is not None:
        stmt = stmt.where(ev.actor_user_id == actor_user_id)
    if event is not None:
        stmt = stmt.where(ev.event == event)
    if desde is not None:
        stmt = stmt.where(ev.created_at >= desde)
    if hasta is not None:
        stmt = stmt.where(ev.created_at < hasta)
    filas, siguiente = await paginate_entities(session, stmt, ev.created_at, ev.id, cursor, limit)
    return AuditPage(
        items=[AuditEventRead.model_validate(f) for f in filas], next_cursor=siguiente
    )
