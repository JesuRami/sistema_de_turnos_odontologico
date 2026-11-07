"""Guardas del reenvío manual de un recordatorio (C-11, D4/D6; spec manual-actions).

Función pura: la usan el endpoint de reenvío (dentro de su transacción con `FOR UPDATE`) y el
timeline (para `can_resend`/`resend_blocked_reason`), así la UI nunca inventa reglas. El orden de
las guardas es parte del contrato: consentimiento, destinatario, cooldown y tope se evalúan antes
que el estado del job, para que un reenvío ya encolado responda `resend_cooldown` y no
`reminder_pending`.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.models import AppointmentOrigin, AppointmentStatus, ReminderChannel, ReminderStatus
from app.modules.reminders.scheduling import requests_confirmation
from app.modules.reminders.templates import STEP_CREATED

_ACTIVE = frozenset({AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED})


@dataclass(frozen=True, slots=True)
class ResendContext:
    """Lo que el reenvío necesita saber del turno, la clínica y el paciente (sin exponerlo)."""

    appointment_status: AppointmentStatus
    origin: AppointmentOrigin
    starts_at: datetime
    configured_steps: Collection[str]
    whatsapp_opt_in: bool
    has_phone: bool
    has_email: bool
    email_opted_out: bool
    tz: ZoneInfo


@dataclass(frozen=True, slots=True)
class JobState:
    status: ReminderStatus
    manual_resend_at: datetime | None


@dataclass(frozen=True, slots=True)
class ResendBlock:
    """Motivo de rechazo con su código HTTP; `retry_after_s` solo para el cooldown."""

    status_code: int
    code: str
    retry_after_s: int | None = None


@dataclass(frozen=True, slots=True)
class ResendStats:
    """Reenvíos manuales previos del job: el último y cuántos van en el día local."""

    last_at: datetime | None
    today: int

    @classmethod
    def of(cls, created: Sequence[datetime], now: datetime, tz: ZoneInfo) -> ResendStats:
        desde, hasta = local_day(now, tz)
        return cls(
            last_at=max(created, default=None),
            today=sum(1 for c in created if desde <= c < hasta),
        )


def local_day(now: datetime, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """`[00:00, 24:00)` del día local de `now` en la zona de la clínica, como instantes."""
    dia = now.astimezone(tz).date()
    inicio = datetime.combine(dia, time(0), tzinfo=tz)
    return inicio, datetime.combine(dia + timedelta(days=1), time(0), tzinfo=tz)


def _confirmed_online(ctx: ResendContext) -> bool:
    return (
        ctx.origin is AppointmentOrigin.ONLINE
        and ctx.appointment_status is AppointmentStatus.CONFIRMED
    )


def resend_block(
    ctx: ResendContext,
    step: str,
    channel: ReminderChannel,
    job: JobState | None,
    stats: ResendStats,
    *,
    now: datetime,
    cooldown_s: int,
    max_per_day: int,
) -> ResendBlock | None:
    """Primer motivo que impide reenviar, en el orden de D4; `None` si se puede."""
    if ctx.appointment_status not in _ACTIVE:
        return ResendBlock(409, "appointment_inactive")
    if now >= ctx.starts_at:
        return ResendBlock(409, "appointment_started")
    if job is None:
        return ResendBlock(404, "reminder_not_found")
    if step != STEP_CREATED and step not in ctx.configured_steps:
        return ResendBlock(409, "step_not_applicable")
    if job.status is ReminderStatus.CANCELLED:
        return ResendBlock(409, "step_not_applicable")
    if requests_confirmation(step) and _confirmed_online(ctx):
        return ResendBlock(409, "step_not_applicable")
    if channel is ReminderChannel.WHATSAPP:
        if not ctx.whatsapp_opt_in:
            return ResendBlock(409, "no_consent")
        if not ctx.has_phone:
            return ResendBlock(409, "no_recipient")
    else:
        if not ctx.has_email:
            return ResendBlock(409, "no_recipient")
        if ctx.email_opted_out:
            return ResendBlock(409, "no_consent")
    en_cola = job.status is ReminderStatus.SCHEDULED and job.manual_resend_at is not None
    if stats.last_at is not None and now - stats.last_at < timedelta(seconds=cooldown_s):
        restante = timedelta(seconds=cooldown_s) - (now - stats.last_at)
        return ResendBlock(409, "resend_cooldown", max(1, math.ceil(restante.total_seconds())))
    if en_cola:
        return ResendBlock(409, "resend_cooldown", max(1, cooldown_s))
    if stats.today >= max_per_day:
        return ResendBlock(409, "resend_limit")
    if job.status is ReminderStatus.SENDING:
        return ResendBlock(409, "reminder_in_flight")
    if job.status is ReminderStatus.SCHEDULED:
        return ResendBlock(409, "reminder_pending")
    return None
