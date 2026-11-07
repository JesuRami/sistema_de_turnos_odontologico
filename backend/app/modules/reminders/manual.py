"""Reenvío manual de un recordatorio desde recepción (C-11, D4/D6; spec manual-actions).

Una transacción: `FOR UPDATE` del turno y luego del job (mismo orden que las mutaciones del turno,
sin deadlocks con `reconcile`), guardas en el orden de D4, fila de auditoría append-only y reset
del job a `scheduled` con `available_at = now`. La request no llama al proveedor ni al SMTP: el
worker lo envía en su próximo tick, con su lease, backoff e idempotencia.

Dos pedidos concurrentes se serializan en el lock del turno: el segundo ve la fila del primero y
cae en `resend_cooldown`. La nota se valida antes de tocar nada y el error nunca repite su valor
(regla 13); ni la nota ni datos del paciente van a logs.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import DomainError
from app.core.settings import Settings
from app.models import ReminderChannel, ReminderJob, ReminderManualResend, ReminderStatus
from app.models.reminder_manual_resend import NOTE_MAX_LENGTH
from app.modules.appointments.audit import Actor
from app.modules.reminders.context import resend_context, scoped_appointment
from app.modules.reminders.guards import JobState, ResendStats, resend_block
from app.modules.reminders.schemas import ResendAccepted

_EMAIL_RE = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
# Secuencias de dígitos con separadores típicos de teléfonos y DNI (`+54 11 5555-0101`,
# `30.123.456`); con 7 dígitos o más se consideran un dato personal.
_DIGITS_RE = re.compile(r"\+?\d[\d\s.\-()/]*\d")
_PII_MIN_DIGITS = 7


def validate_note(note: str | None) -> str | None:
    """Nota operativa opcional: ≤ 200 caracteres y sin teléfono, email ni DNI."""
    if note is None:
        return None
    limpia = note.strip()
    if not limpia:
        return None
    if len(limpia) > NOTE_MAX_LENGTH or _EMAIL_RE.search(limpia):
        raise DomainError(422, "invalid_note")
    for tramo in _DIGITS_RE.findall(limpia):
        if sum(c.isdigit() for c in tramo) >= _PII_MIN_DIGITS:
            raise DomainError(422, "invalid_note")
    return limpia


async def resend(
    session: AsyncSession,
    actor: Actor,
    appointment_id: uuid.UUID,
    step: str,
    channel: ReminderChannel,
    note: str | None,
    *,
    now: datetime,
    settings: Settings,
) -> ResendAccepted:
    nota = validate_note(note)
    if actor.user_id is None:
        raise DomainError(403, "forbidden_role")
    turno = await scoped_appointment(session, actor, appointment_id, lock=True)
    job = (
        await session.execute(
            select(ReminderJob.id, ReminderJob.status, ReminderJob.manual_resend_at)
            .where(
                ReminderJob.clinic_id == turno.clinic_id,
                ReminderJob.appointment_id == turno.id,
                ReminderJob.step == step,
                ReminderJob.channel == channel,
            )
            .with_for_update()
        )
    ).one_or_none()
    ctx = await resend_context(session, turno)
    previos: list[datetime] = []
    if job is not None:
        previos = list(
            (
                await session.scalars(
                    select(ReminderManualResend.created_at).where(
                        ReminderManualResend.clinic_id == turno.clinic_id,
                        ReminderManualResend.reminder_job_id == job.id,
                    )
                )
            ).all()
        )
    stats = ResendStats.of(previos, now, ctx.tz)
    bloqueo = resend_block(
        ctx,
        step,
        channel,
        None if job is None else JobState(job.status, job.manual_resend_at),
        stats,
        now=now,
        cooldown_s=settings.REMINDER_MANUAL_RESEND_COOLDOWN_S,
        max_per_day=settings.REMINDER_MANUAL_RESEND_MAX_PER_DAY,
    )
    if bloqueo is not None:
        extra = None if bloqueo.retry_after_s is None else {"retry_after_s": bloqueo.retry_after_s}
        raise DomainError(bloqueo.status_code, bloqueo.code, extra=extra)
    assert job is not None  # la guarda 3 lo garantiza

    session.add(
        ReminderManualResend(
            clinic_id=turno.clinic_id,
            appointment_id=turno.id,
            reminder_job_id=job.id,
            actor_user_id=actor.user_id,
            note=nota,
            created_at=now,
        )
    )
    await session.execute(
        update(ReminderJob)
        .where(ReminderJob.clinic_id == turno.clinic_id, ReminderJob.id == job.id)
        .values(
            status=ReminderStatus.SCHEDULED,
            available_at=now,
            attempts=0,
            claimed_at=None,
            last_error=None,
            sent_at=None,
            provider_message_id=None,
            cost_micros=None,
            reason=None,
            manual_resend_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    await session.commit()
    return ResendAccepted(
        job_id=job.id,
        status="scheduled",
        available_at=now,
        manual_resends_today=stats.today + 1,
        cooldown_until=now + timedelta(seconds=settings.REMINDER_MANUAL_RESEND_COOLDOWN_S),
    )
