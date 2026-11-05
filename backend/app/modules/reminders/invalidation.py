"""Punto de invalidación de recordatorios (C-08, D11): puerto, no tabla.

Confirmar, cancelar y reprogramar un turno por token lo invocan dentro de la transacción de
la mutación, después de mutar y antes del commit: si falla, la mutación se revierte. En v1 es
no-op (no existe `reminder_job`); C-09 reemplaza `get_reminder_invalidator` por la
implementación real (cancelar los jobs pendientes y reprogramar los futuros) sin tocar el
router, el servicio de gestión ni los specs.
"""

from __future__ import annotations

from typing import Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Appointment

InvalidationAction = Literal["confirm", "cancel", "reschedule"]


class ReminderInvalidator(Protocol):
    async def invalidated(
        self, session: AsyncSession, appointment: Appointment, *, action: InvalidationAction
    ) -> None: ...


class NoopReminderInvalidator:
    """v1: todavía no hay recordatorios programados que invalidar."""

    async def invalidated(
        self, session: AsyncSession, appointment: Appointment, *, action: InvalidationAction
    ) -> None:
        return None


def get_reminder_invalidator() -> ReminderInvalidator:
    """Dependency: la implementación vigente (C-09 la reemplaza)."""
    return NoopReminderInvalidator()
