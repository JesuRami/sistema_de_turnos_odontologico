"""Programación estado-basada de los `reminder_job` de un turno (C-09, D2).

`reconcile` calcula el conjunto deseado de jobs a partir del ESTADO actual del turno y lo
compara con las filas existentes; no recibe la acción que originó el cambio. Por eso es
idempotente por construcción (llamarla dos veces no cambia nada la segunda), cubre reprogramar,
confirmar, cancelar y un cambio de `clinic.reminder_steps` con el mismo código, y no depende de
que cada caller pase la acción correcta.

Corre dentro de la transacción de la mutación (sin commit): si falla, la mutación revierte. Solo
toca jobs `scheduled`; uno `sending`, `sent` o ya cerrado no se pisa. Filtra siempre por
`clinic_id` (regla 4) y selecciona columnas explícitas (regla 8).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Appointment,
    AppointmentOrigin,
    AppointmentStatus,
    Clinic,
    ReminderChannel,
    ReminderJob,
    ReminderReason,
    ReminderStatus,
)
from app.modules.reminders.jobs import close_scheduled
from app.modules.reminders.templates import STEP_CREATED

# Un paso "pide confirmar" si es el alta o si avisa con 24 h o más de anticipación; el de 3 h
# ("te esperamos") se sigue enviando aunque el paciente ya haya confirmado.
CONFIRM_REQUEST_MIN_OFFSET_H = 24
_ACTIVE = frozenset({AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED})
_STEP_RE = re.compile(r"^t_([0-9]+)h$")

Key = tuple[str, ReminderChannel]


def step_for_offset(offset_h: int) -> str:
    return f"t_{offset_h}h"


def requests_confirmation(step: str) -> bool:
    if step == STEP_CREATED:
        return True
    encontrado = _STEP_RE.match(step)
    return encontrado is not None and int(encontrado.group(1)) >= CONFIRM_REQUEST_MIN_OFFSET_H


def _confirmed_online(appointment: Appointment) -> bool:
    """Un turno online que ya pasó de `pending` a `confirmed` no necesita más pedidos de confirmar.

    Un turno de recepción nace `confirmed` (RN-ST-02) y debe recibir todos sus pasos: el único
    que transita `pending → confirmed` es el online, así `origin + status` lo distingue.
    """
    return (
        appointment.origin is AppointmentOrigin.ONLINE
        and appointment.status is AppointmentStatus.CONFIRMED
    )


def _configured(steps: list[dict[str, Any]]) -> dict[Key, int]:
    """`(paso, canal) → offset_h` de `clinic.reminder_steps`, ignorando entradas inválidas."""
    configurados: dict[Key, int] = {}
    for entrada in steps:
        try:
            offset = int(entrada["offset_h"])
            canal = ReminderChannel(entrada["channel"])
        except (KeyError, TypeError, ValueError):
            continue
        if offset > 0:
            configurados[(step_for_offset(offset), canal)] = offset
    return configurados


def _wanted(
    appointment: Appointment, configured: dict[Key, int], now: datetime
) -> dict[Key, datetime]:
    """Pasos que deberían existir hoy: turno activo, hora futura y que no pidan confirmar de más."""
    if appointment.status not in _ACTIVE or appointment.starts_at <= now:
        return {}
    deseados: dict[Key, datetime] = {}
    for (paso, canal), offset in configured.items():
        cuando = appointment.starts_at - timedelta(hours=offset)
        if cuando <= now:
            continue
        if _confirmed_online(appointment) and requests_confirmation(paso):
            continue
        deseados[(paso, canal)] = cuando
    return deseados


async def _load(
    session: AsyncSession, appointment: Appointment
) -> tuple[list[dict[str, Any]], dict[Key, Any]]:
    steps = await session.scalar(
        select(Clinic.reminder_steps).where(Clinic.id == appointment.clinic_id)
    )
    filas = (
        await session.execute(
            select(
                ReminderJob.id,
                ReminderJob.step,
                ReminderJob.channel,
                ReminderJob.status,
                ReminderJob.scheduled_for,
                ReminderJob.starts_at_snapshot,
            ).where(
                ReminderJob.clinic_id == appointment.clinic_id,
                ReminderJob.appointment_id == appointment.id,
            )
        )
    ).all()
    return list(steps or []), {(f.step, f.channel): f for f in filas}


async def reconcile(session: AsyncSession, appointment: Appointment, *, now: datetime) -> None:
    """Deja los jobs del turno coherentes con su estado actual (idempotente)."""
    steps, existentes = await _load(session, appointment)
    configurados = _configured(steps)
    deseados = _wanted(appointment, configurados, now)
    activo = appointment.status in _ACTIVE
    alta_vigente = activo and appointment.starts_at > now and not _confirmed_online(appointment)

    a_cancelar: dict[ReminderReason, list[uuid.UUID]] = {}
    for clave, fila in existentes.items():
        if fila.status is not ReminderStatus.SCHEDULED:
            continue
        paso, _canal = clave
        if paso == STEP_CREATED:
            if alta_vigente:
                await _refresh(session, appointment, fila, fila.scheduled_for)
            elif not activo:
                a_cancelar.setdefault(ReminderReason.APPOINTMENT_INACTIVE, []).append(fila.id)
            elif appointment.starts_at > now:
                a_cancelar.setdefault(ReminderReason.CONFIRMED, []).append(fila.id)
            else:
                a_cancelar.setdefault(ReminderReason.STEP_ELAPSED, []).append(fila.id)
        elif clave in deseados:
            await _refresh(session, appointment, fila, deseados[clave])
        elif not activo:
            a_cancelar.setdefault(ReminderReason.APPOINTMENT_INACTIVE, []).append(fila.id)
        elif clave not in configurados:
            a_cancelar.setdefault(ReminderReason.STEP_REMOVED, []).append(fila.id)
        elif _confirmed_online(appointment) and requests_confirmation(paso):
            a_cancelar.setdefault(ReminderReason.CONFIRMED, []).append(fila.id)
        else:
            a_cancelar.setdefault(ReminderReason.STEP_ELAPSED, []).append(fila.id)

    for motivo, ids in a_cancelar.items():
        await close_scheduled(
            session,
            [ReminderJob.clinic_id == appointment.clinic_id, ReminderJob.id.in_(ids)],
            to=ReminderStatus.CANCELLED,
            reason=motivo,
        )

    nuevos = [
        _row(appointment, paso, canal, cuando)
        for (paso, canal), cuando in deseados.items()
        if (paso, canal) not in existentes
    ]
    await _insert(session, nuevos)


async def schedule_new(session: AsyncSession, appointment: Appointment, *, now: datetime) -> None:
    """Programa un turno recién creado: el alta (al instante) y luego los pasos futuros."""
    if (
        appointment.status in _ACTIVE
        and appointment.starts_at > now
        and not _confirmed_online(appointment)
    ):
        await _insert(session, [_row(appointment, STEP_CREATED, ReminderChannel.WHATSAPP, now)])
    await reconcile(session, appointment, now=now)


def _row(
    appointment: Appointment, paso: str, canal: ReminderChannel, cuando: datetime
) -> dict[str, Any]:
    return {
        "clinic_id": appointment.clinic_id,
        "appointment_id": appointment.id,
        "step": paso,
        "channel": canal,
        "scheduled_for": cuando,
        "available_at": cuando,
        "starts_at_snapshot": appointment.starts_at,
    }


async def _insert(session: AsyncSession, filas: list[dict[str, Any]]) -> None:
    if not filas:
        return
    await session.execute(
        pg_insert(ReminderJob)
        .values(filas)
        .on_conflict_do_nothing(index_elements=["appointment_id", "step", "channel"])
    )


async def _refresh(
    session: AsyncSession, appointment: Appointment, fila: Any, cuando: datetime
) -> None:
    """Actualiza hora y snapshot de un job `scheduled` solo si cambiaron."""
    if fila.scheduled_for == cuando and fila.starts_at_snapshot == appointment.starts_at:
        return
    await session.execute(
        update(ReminderJob)
        .where(
            ReminderJob.id == fila.id,
            ReminderJob.clinic_id == appointment.clinic_id,
            ReminderJob.status == ReminderStatus.SCHEDULED,
        )
        .values(
            scheduled_for=cuando,
            available_at=cuando,
            starts_at_snapshot=appointment.starts_at,
        )
        .execution_options(synchronize_session=False)
    )
