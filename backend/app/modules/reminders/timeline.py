"""Read model del timeline de recordatorios de un turno (C-11, D2/D3; spec delivery-timeline).

Tres consultas por turno, sin N+1: jobs, eventos de esos jobs y reenvíos manuales con el rol del
actor. El estado de cada paso se deriva de los eventos, no solo del `status` mutable:

- **Generación vigente**: los eventos con `occurred_at` posterior al último reenvío manual del job.
  Lo anterior se marca `previous` ("envío anterior") y no incide en el estado vigente.
- **Precedencia** dentro de la generación vigente, respecto del último `sent`: `read` >
  `delivered` > `failed`; sin `sent`, el estado del job. Meta informa sus estados con segundos
  enteros, así que el `sent` se compara truncado al segundo: un `delivered` del mismo segundo no se
  pierde por el redondeo.
- `scheduled` no es un evento: se sintetiza como primer hito cuando el job está `scheduled` o
  `sending`.

`detail` expone solo claves seguras del `payload` (intento, tipo, motivo, costo, destino lógico,
marca manual); nunca `provider_message_id`, links ni datos del paciente (regla 13). La nota del
reenvío no se expone.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import Settings
from app.models import (
    AppointmentStatus,
    DeliveryEvent,
    DeliveryEventType,
    ReminderChannel,
    ReminderJob,
    ReminderManualResend,
    ReminderStatus,
    User,
)
from app.modules.appointments.audit import Actor
from app.modules.reminders.context import resend_context, scoped_appointment
from app.modules.reminders.guards import JobState, ResendStats, resend_block
from app.modules.reminders.schemas import (
    DetailValue,
    TimelineEventRead,
    TimelineRead,
    TimelineStepRead,
)
from app.modules.reminders.templates import STEP_CREATED

MANUAL_RESEND = "manual_resend"
SCHEDULED = "scheduled"
_SAFE_DETAIL = ("attempt", "kind", "reason", "cost_micros", "to", "manual")
_CHANNEL_ORDER = {ReminderChannel.WHATSAPP: 0, ReminderChannel.EMAIL: 1}
_PENDING = (ReminderStatus.SCHEDULED, ReminderStatus.SENDING)


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    type: str
    occurred_at: datetime
    detail: dict[str, DetailValue]
    previous: bool = False


def _floor_second(instant: datetime) -> datetime:
    return instant.replace(microsecond=0)


def effective_status(
    job_status: ReminderStatus, events: Sequence[TimelineEvent], cut: datetime | None
) -> str:
    """Estado efectivo del intento vigente (D2)."""
    vigentes = [
        e
        for e in events
        if e.type not in (MANUAL_RESEND, SCHEDULED) and (cut is None or e.occurred_at >= cut)
    ]
    envios = [e.occurred_at for e in vigentes if e.type == DeliveryEventType.SENT.value]
    if not envios:
        return job_status.value
    umbral = _floor_second(max(envios))
    posteriores = {e.type for e in vigentes if e.occurred_at >= umbral}
    for tipo in (DeliveryEventType.READ, DeliveryEventType.DELIVERED, DeliveryEventType.FAILED):
        if tipo.value in posteriores:
            return tipo.value
    return job_status.value


def mark_generations(events: Iterable[TimelineEvent], cut: datetime | None) -> list[TimelineEvent]:
    """Marca como envío anterior lo previo al último reenvío (y los propios reenvíos)."""
    if cut is None:
        return list(events)
    return [replace(e, previous=e.type == MANUAL_RESEND or e.occurred_at < cut) for e in events]


def _safe_detail(payload: dict[str, Any]) -> dict[str, DetailValue]:
    detalle: dict[str, DetailValue] = {}
    for clave in _SAFE_DETAIL:
        valor = payload.get(clave)
        if isinstance(valor, str | int | bool):
            detalle[clave] = valor
    return detalle


def step_sort_key(step: str, channel: ReminderChannel) -> tuple[int, int, str, int]:
    """Alta primero, luego de mayor a menor anticipación; WhatsApp antes que email (D3)."""
    if step == STEP_CREATED:
        return (0, 0, step, _CHANNEL_ORDER[channel])
    if step.startswith("t_") and step.endswith("h") and step[2:-1].isdigit():
        return (1, -int(step[2:-1]), step, _CHANNEL_ORDER[channel])
    return (2, 0, step, _CHANNEL_ORDER[channel])


async def build_timeline(
    session: AsyncSession,
    actor: Actor,
    appointment_id: uuid.UUID,
    *,
    now: datetime,
    settings: Settings,
) -> TimelineRead:
    turno = await scoped_appointment(session, actor, appointment_id)
    ctx = await resend_context(session, turno)
    jobs = (
        await session.execute(
            select(
                ReminderJob.id,
                ReminderJob.step,
                ReminderJob.channel,
                ReminderJob.status,
                ReminderJob.reason,
                ReminderJob.scheduled_for,
                ReminderJob.available_at,
                ReminderJob.sent_at,
                ReminderJob.attempts,
                ReminderJob.last_error,
                ReminderJob.manual_resend_at,
            ).where(
                ReminderJob.clinic_id == turno.clinic_id,
                ReminderJob.appointment_id == turno.id,
            )
        )
    ).all()
    ids = [j.id for j in jobs]
    eventos: dict[uuid.UUID, list[TimelineEvent]] = {i: [] for i in ids}
    if ids:
        for fila in (
            await session.execute(
                select(
                    DeliveryEvent.reminder_job_id,
                    DeliveryEvent.event_type,
                    DeliveryEvent.occurred_at,
                    DeliveryEvent.payload,
                )
                .where(
                    DeliveryEvent.clinic_id == turno.clinic_id,
                    DeliveryEvent.reminder_job_id.in_(ids),
                )
                .order_by(DeliveryEvent.occurred_at, DeliveryEvent.received_at, DeliveryEvent.id)
            )
        ).all():
            eventos[fila.reminder_job_id].append(
                TimelineEvent(
                    type=fila.event_type.value,
                    occurred_at=fila.occurred_at,
                    detail=_safe_detail(fila.payload or {}),
                )
            )
    reenvios: dict[uuid.UUID, list[datetime]] = {i: [] for i in ids}
    for fila in (
        await session.execute(
            select(
                ReminderManualResend.reminder_job_id,
                ReminderManualResend.created_at,
                User.role,
            )
            .join(
                User,
                (User.clinic_id == ReminderManualResend.clinic_id)
                & (User.id == ReminderManualResend.actor_user_id),
            )
            .where(
                ReminderManualResend.clinic_id == turno.clinic_id,
                ReminderManualResend.appointment_id == turno.id,
            )
            .order_by(ReminderManualResend.created_at, ReminderManualResend.id)
        )
    ).all():
        reenvios.setdefault(fila.reminder_job_id, []).append(fila.created_at)
        eventos.setdefault(fila.reminder_job_id, []).append(
            TimelineEvent(
                type=MANUAL_RESEND,
                occurred_at=fila.created_at,
                detail={"actor_role": fila.role.value},
            )
        )

    pasos: list[TimelineStepRead] = []
    for j in sorted(jobs, key=lambda j: step_sort_key(j.step, j.channel)):
        historial = sorted(eventos.get(j.id, []), key=lambda e: e.occurred_at)
        corte = max(reenvios.get(j.id, []), default=None)
        stats = ResendStats.of(reenvios.get(j.id, []), now, ctx.tz)
        bloqueo = resend_block(
            ctx,
            j.step,
            j.channel,
            JobState(j.status, j.manual_resend_at),
            stats,
            now=now,
            cooldown_s=settings.REMINDER_MANUAL_RESEND_COOLDOWN_S,
            max_per_day=settings.REMINDER_MANUAL_RESEND_MAX_PER_DAY,
        )
        marcados = mark_generations(historial, corte)
        if j.status in _PENDING:
            marcados.insert(0, TimelineEvent(type=SCHEDULED, occurred_at=j.available_at, detail={}))
        pasos.append(
            TimelineStepRead(
                step=j.step,
                channel=j.channel,
                status=effective_status(j.status, historial, corte),
                reason=j.reason,
                scheduled_for=j.scheduled_for,
                available_at=j.available_at,
                sent_at=j.sent_at,
                attempts=j.attempts,
                last_error=j.last_error,
                manual_resends_today=stats.today,
                last_manual_resend_at=stats.last_at,
                can_resend=actor.is_front_desk and bloqueo is None,
                resend_blocked_reason=(
                    None if not actor.is_front_desk or bloqueo is None else bloqueo.code
                ),
                events=[
                    TimelineEventRead(
                        type=e.type,
                        occurred_at=e.occurred_at,
                        previous=e.previous,
                        detail=e.detail,
                    )
                    for e in marcados
                ],
            )
        )
    return TimelineRead(
        appointment_id=turno.id,
        timezone=str(ctx.tz),
        pending_confirmation=turno.status is AppointmentStatus.PENDING,
        steps=pasos,
    )
