"""Lista de seguimiento de recordatorios para recepción (C-11, D8; spec followup-board).

Parte del rango de turnos (índice de agenda por `clinic_id, starts_at`) y calcula dos motivos con
`EXISTS` por turno:

- **`no_response`**: turno `pending` con un evento `sent` del paso de confirmación: `t_24h` si la
  clínica lo configura; si no, cualquier paso que pide confirmación. Un job de ese paso que quedó
  `failed` no cuenta como "no respondió": es un fallo de envío.
- **`delivery_failed`**: algún job del turno `failed` programado antes del inicio (índice parcial
  `ix_reminder_job_failed`). Desaparece cuando el reenvío funciona (el job deja de estar `failed`).

Solo turnos vigentes (`pending`/`confirmed`) y futuros. Orden `starts_at, id` con cursor (regla 8);
los totales cubren todo el rango. La fila lleva el nombre del paciente y nada más de contacto
(regla 13); el endpoint no loguea datos personales.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Integer, and_, cast, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import DomainError
from app.common.pagination import decode_cursor, encode_cursor
from app.models import (
    Appointment,
    AppointmentStatus,
    Clinic,
    DeliveryEvent,
    DeliveryEventType,
    Patient,
    ReminderJob,
    ReminderStatus,
)
from app.modules.reminders.scheduling import (
    CONFIRM_REQUEST_MIN_OFFSET_H,
    configured_step_names,
)
from app.modules.reminders.schemas import (
    FollowUpPage,
    FollowUpReason,
    FollowUpRow,
    FollowUpTotals,
    LastReminderRead,
)
from app.modules.reminders.templates import STEP_CREATED

MAX_RANGE = timedelta(days=31)
_ACTIVE = (AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED)
_ATTEMPTED = (
    ReminderStatus.SENT,
    ReminderStatus.DELIVERED,
    ReminderStatus.READ,
    ReminderStatus.FAILED,
    ReminderStatus.SKIPPED,
)


def _confirmation_step(prefer_24h: bool) -> Any:
    """Condición SQL del paso de confirmación sobre `reminder_job.step`."""
    if prefer_24h:
        return ReminderJob.step == "t_24h"
    # `step_format` garantiza `created` o `t_<n>h`; los dígitos se comparan como entero.
    horas = cast(func.substring(ReminderJob.step, r"^t_([0-9]+)h$"), Integer)
    return or_(ReminderJob.step == STEP_CREATED, horas >= CONFIRM_REQUEST_MIN_OFFSET_H)


def _reasons(prefer_24h: bool) -> tuple[Any, Any]:
    enviado = (
        exists()
        .where(
            ReminderJob.clinic_id == Appointment.clinic_id,
            ReminderJob.appointment_id == Appointment.id,
            ReminderJob.status != ReminderStatus.FAILED,
            _confirmation_step(prefer_24h),
            DeliveryEvent.clinic_id == ReminderJob.clinic_id,
            DeliveryEvent.reminder_job_id == ReminderJob.id,
            DeliveryEvent.event_type == DeliveryEventType.SENT,
        )
        .correlate(Appointment)
    )
    no_response = and_(Appointment.status == AppointmentStatus.PENDING, enviado)
    delivery_failed = (
        exists()
        .where(
            ReminderJob.clinic_id == Appointment.clinic_id,
            ReminderJob.appointment_id == Appointment.id,
            ReminderJob.status == ReminderStatus.FAILED,
            ReminderJob.scheduled_for < Appointment.starts_at,
        )
        .correlate(Appointment)
    )
    return no_response, delivery_failed


async def follow_up(
    session: AsyncSession,
    clinic_id: uuid.UUID,
    desde: datetime,
    hasta: datetime,
    cursor: str | None,
    limit: int,
    *,
    now: datetime,
) -> FollowUpPage:
    if desde > hasta:
        raise DomainError(422, "invalid_range")
    if hasta - desde > MAX_RANGE:
        raise DomainError(422, "range_too_large")
    pasos = await session.scalar(select(Clinic.reminder_steps).where(Clinic.id == clinic_id))
    no_response, delivery_failed = _reasons("t_24h" in configured_step_names(list(pasos or [])))
    base = [
        Appointment.clinic_id == clinic_id,
        Appointment.starts_at >= desde,
        Appointment.starts_at < hasta,
        Appointment.starts_at > now,
        Appointment.status.in_(_ACTIVE),
    ]
    totales = (
        await session.execute(
            select(
                func.count().filter(no_response).label("no_response"),
                func.count().filter(delivery_failed).label("delivery_failed"),
            ).where(*base)
        )
    ).one()

    pagina: Any = (
        select(
            Appointment.id,
            Appointment.starts_at,
            Appointment.patient_id,
            Patient.full_name,
            Appointment.professional_id,
            Appointment.status,
            no_response.label("no_response"),
            delivery_failed.label("delivery_failed"),
        )
        .join(
            Patient,
            and_(Patient.clinic_id == Appointment.clinic_id, Patient.id == Appointment.patient_id),
        )
        .where(*base, or_(no_response, delivery_failed))
    )
    if cursor:
        ts, ultimo = decode_cursor(cursor)
        pagina = pagina.where(
            or_(
                Appointment.starts_at > ts,
                and_(Appointment.starts_at == ts, Appointment.id > ultimo),
            )
        )
    filas = (
        await session.execute(
            pagina.order_by(Appointment.starts_at, Appointment.id).limit(limit + 1)
        )
    ).all()
    siguiente = None
    if len(filas) > limit:
        filas = filas[:limit]
        siguiente = encode_cursor(filas[-1].starts_at, filas[-1].id)

    ultimos = await _last_reminders(session, clinic_id, [f.id for f in filas])
    items: list[FollowUpRow] = []
    for f in filas:
        motivos: list[FollowUpReason] = []
        if f.no_response:
            motivos.append("no_response")
        if f.delivery_failed:
            motivos.append("delivery_failed")
        items.append(
            FollowUpRow(
                appointment_id=f.id,
                starts_at=f.starts_at,
                patient_id=f.patient_id,
                patient_name=f.full_name,
                professional_id=f.professional_id,
                status=f.status,
                reasons=motivos,
                last_reminder=ultimos.get(f.id),
                can_confirm=f.status is AppointmentStatus.PENDING,
            )
        )
    return FollowUpPage(
        items=items,
        totals=FollowUpTotals(
            no_response=int(totales.no_response), delivery_failed=int(totales.delivery_failed)
        ),
        next_cursor=siguiente,
    )


async def _last_reminders(
    session: AsyncSession, clinic_id: uuid.UUID, ids: list[uuid.UUID]
) -> dict[uuid.UUID, LastReminderRead]:
    """Último recordatorio intentado de cada turno de la página (una consulta)."""
    if not ids:
        return {}
    momento = func.coalesce(ReminderJob.sent_at, ReminderJob.available_at)
    filas = (
        await session.execute(
            select(
                ReminderJob.appointment_id,
                ReminderJob.step,
                ReminderJob.channel,
                ReminderJob.status,
                ReminderJob.sent_at,
                ReminderJob.last_error,
            )
            .distinct(ReminderJob.appointment_id)
            .where(
                ReminderJob.clinic_id == clinic_id,
                ReminderJob.appointment_id.in_(ids),
                ReminderJob.status.in_(_ATTEMPTED),
            )
            .order_by(ReminderJob.appointment_id, momento.desc(), ReminderJob.id)
        )
    ).all()
    return {
        f.appointment_id: LastReminderRead(
            step=f.step,
            channel=f.channel,
            status=f.status.value,
            sent_at=f.sent_at,
            last_error=f.last_error,
        )
        for f in filas
    }
