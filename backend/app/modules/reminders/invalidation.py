"""Punto de invalidación de recordatorios (C-08 D11, C-09 D3): puerto con implementación real.

Confirmar, cancelar y reprogramar un turno por token lo invocan dentro de la transacción de la
mutación, después de mutar y antes del commit: si falla, la mutación se revierte.

C-09 lo reemplaza sin tocar el router, el servicio de gestión ni la superficie pública: la
implementación vigente reconcilia los `reminder_job` del turno contra su estado actual. El
núcleo de escritura de turnos (C-05) ya reconcilia en cada mutación, así que esta llamada es
redundante pero idempotente (la segunda vez no cambia nada) y mantiene el contrato de C-08 y el
spy de sus tests. El reloj es el mismo `get_now` del request, para no mezclar instantes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.clock import get_now
from app.models import Appointment
from app.modules.reminders.scheduling import reconcile

InvalidationAction = Literal["confirm", "cancel", "reschedule"]


class ReminderInvalidator(Protocol):
    async def invalidated(
        self, session: AsyncSession, appointment: Appointment, *, action: InvalidationAction
    ) -> None: ...


class NoopReminderInvalidator:
    """Sin recordatorios que invalidar: lo usa `ManageService` cuando no se le inyecta otro."""

    async def invalidated(
        self, session: AsyncSession, appointment: Appointment, *, action: InvalidationAction
    ) -> None:
        return None


class ReconcilingInvalidator:
    """Reconcilia los jobs del turno contra su estado actual (cancela, recalcula, repone)."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    async def invalidated(
        self, session: AsyncSession, appointment: Appointment, *, action: InvalidationAction
    ) -> None:
        _ = action  # reconcile es estado-basado: no depende de la acción (D2)
        await reconcile(session, appointment, now=self.now)


def get_reminder_invalidator(now: Annotated[datetime, Depends(get_now)]) -> ReminderInvalidator:
    """Dependency: la implementación vigente."""
    return ReconcilingInvalidator(now)
