"""Despacho de recordatorios: reclamo con lease, validación previa, envío y resultado (C-09, D4-D7).

Un tick:

1. **Recupera leases**: un job `sending` cuyo reclamo superó `REMINDER_LEASE_MINUTES` (worker caído
   a mitad de lote) vuelve a `scheduled`, o queda `failed` si ya agotó sus intentos.
2. **Reclama** hasta `REMINDER_BATCH_SIZE` jobs vencidos con `FOR UPDATE SKIP LOCKED` en una
   transacción corta: valida cada uno (turno vigente y no iniciado, horario vigente, consentimiento,
   destinatario, plantilla activa) y deja los que pasan en `sending` con un intento más.
3. **Envía** fuera de esa transacción (no se mantienen locks durante el HTTP/SMTP), con un
   re-chequeo del turno justo antes y concurrencia acotada.
4. **Registra el resultado** en otra transacción: `sent`, reintento con backoff o `failed` con
   escalado a email. El reintento se agenda con `available_at`; `scheduled_for` conserva la hora
   original.

El worker no toma locks sobre `appointment`: la mutación del turno bloquea el turno y después
actualiza jobs, y bloquear en el orden inverso produciría deadlocks. La ventana de milisegundos que
queda entre el re-chequeo y el envío se documenta en el diseño (D4).

Garantía: al menos una vez. Si el worker muere entre el envío y la transacción de resultado, el
lease devuelve el job a `scheduled` y se reenvía.

Regla 13: ni los logs, ni `last_error`, ni `delivery_event.payload` llevan nombre, teléfono, email
ni link. `Ready` y `OutboundMessage` ocultan sus datos en `repr`.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.settings import Settings
from app.models import (
    Appointment,
    AppointmentStatus,
    Clinic,
    Consent,
    ConsentStatus,
    DeliveryEvent,
    DeliveryEventType,
    NotificationTemplate,
    Patient,
    Professional,
    ReminderChannel,
    ReminderJob,
    ReminderReason,
    ReminderStatus,
    WaitingListEntry,
    WaitlistOffer,
    WaitlistOfferStatus,
)
from app.modules.notifications.replies import run_replies
from app.modules.reminders.jobs import add_event, escalate_to_email
from app.modules.reminders.links import ManageLinkDisabled, build_manage_url
from app.modules.reminders.scheduling import reconcile
from app.modules.reminders.senders.base import OutboundMessage, ReminderSender, SendError
from app.modules.reminders.senders.render import MissingVariable, format_date, format_time, render
from app.modules.reminders.templates import param_order_of, whatsapp_buttons
from app.modules.waiting_list.links import build_offer_url

logger = logging.getLogger("reminders.dispatch")

SessionFactory = async_sessionmaker[AsyncSession]
Senders = Mapping[ReminderChannel, ReminderSender]
Clock = Callable[[], datetime]

_ACTIVE = (AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED)
# Tope duro de lotes por tick: evita un bucle sin fin si un bug dejara jobs reclamables.
_MAX_BATCHES = 10_000


@dataclass
class TickStats:
    """Conteos de un tick (solo números; sin datos personales)."""

    batches: int = 0
    claimed: int = 0
    sent: int = 0
    retried: int = 0
    failed: int = 0
    skipped: int = 0
    cancelled: int = 0
    released: int = 0
    escalated: int = 0
    recovered: int = 0


@dataclass(frozen=True, slots=True, repr=False)
class Ready:
    """Un job reclamado y validado, con lo necesario para armar el mensaje (datos personales)."""

    job_id: uuid.UUID
    clinic_id: uuid.UUID
    # Exactamente uno de los dos (C-12, D2): recordatorio de un turno u oferta de lista de espera.
    appointment_id: uuid.UUID | None
    channel: ReminderChannel
    step: str
    attempts: int
    starts_at: datetime
    starts_at_snapshot: datetime
    template_name: str
    body_preview: str
    recipient: str
    patient_first_name: str
    professional_name: str
    clinic_name: str
    tz: ZoneInfo
    patient_email: str | None
    email_blocked: bool
    # `phone_number_id` emisor de WhatsApp: el propio de la clínica o el compartido (C-10).
    sender_id: str | None = None
    # El envío proviene de un reenvío manual de recepción (C-11): el evento `sent` lo marca.
    manual: bool = False
    # Oferta de la lista de espera (C-12): su id y su vencimiento (`{{vence}}`).
    waitlist_offer_id: uuid.UUID | None = None
    expires_at: datetime | None = None

    def __repr__(self) -> str:
        return f"Ready(job={self.job_id}, channel={self.channel.value}, step={self.step})"


@dataclass(frozen=True, slots=True)
class Claimed:
    """Resultado de un lote: cuántos jobs se examinaron y cuáles quedaron listos para enviar."""

    examined: int
    ready: list[Ready]


def _backoff(settings: Settings, attempts: int) -> timedelta:
    """Espera tras el fallo número `attempts` (1.er fallo → primer tramo)."""
    tramos = settings.reminder_backoff_minutes
    return timedelta(minutes=tramos[min(attempts, len(tramos)) - 1])


def _cost(settings: Settings, channel: ReminderChannel) -> int:
    if channel is ReminderChannel.WHATSAPP:
        return settings.REMINDER_COST_WHATSAPP_MICROS
    return settings.REMINDER_COST_EMAIL_MICROS


# ------------------------------------------------------------------------------ leases


async def _recover_leases(
    factory: SessionFactory, now: datetime, settings: Settings, stats: TickStats
) -> None:
    limite = now - timedelta(minutes=settings.REMINDER_LEASE_MINUTES)
    async with factory() as session, session.begin():
        vencidos = and_(
            ReminderJob.status == ReminderStatus.SENDING, ReminderJob.claimed_at < limite
        )
        agotados = await session.execute(
            update(ReminderJob)
            .where(vencidos, ReminderJob.attempts >= settings.REMINDER_MAX_ATTEMPTS)
            .values(
                status=ReminderStatus.FAILED,
                reason=ReminderReason.LEASE_EXPIRED.value,
                claimed_at=None,
                manual_resend_at=None,
            )
            .returning(ReminderJob.id, ReminderJob.clinic_id)
            .execution_options(synchronize_session=False)
        )
        for job_id, clinic_id in agotados.all():
            add_event(
                session,
                job_id,
                clinic_id,
                DeliveryEventType.FAILED,
                {"reason": ReminderReason.LEASE_EXPIRED.value},
            )
            stats.failed += 1
        recuperados = await session.execute(
            update(ReminderJob)
            .where(vencidos)
            .values(
                status=ReminderStatus.SCHEDULED,
                reason=ReminderReason.LEASE_EXPIRED.value,
                claimed_at=None,
            )
            .returning(ReminderJob.id, ReminderJob.clinic_id, ReminderJob.attempts)
            .execution_options(synchronize_session=False)
        )
        for job_id, clinic_id, attempts in recuperados.all():
            add_event(
                session,
                job_id,
                clinic_id,
                DeliveryEventType.LEASE_EXPIRED,
                {"attempts": attempts},
            )
            stats.recovered += 1


# ------------------------------------------------------------------------------ reclamo


def _email_consent(patient_id: Any, *correlate: Any) -> Any:
    """Último estado del consentimiento de email del paciente (subconsulta correlacionada)."""
    return (
        select(Consent.status)
        .where(
            Consent.clinic_id == ReminderJob.clinic_id,
            Consent.patient_id == patient_id,
            Consent.channel == ReminderChannel.EMAIL,
        )
        .order_by(Consent.changed_at.desc(), Consent.id)
        .limit(1)
        .correlate(ReminderJob, *correlate)
        .scalar_subquery()
    )


def _template_join() -> Any:
    return and_(
        NotificationTemplate.clinic_id == ReminderJob.clinic_id,
        NotificationTemplate.channel == ReminderJob.channel,
        NotificationTemplate.step == ReminderJob.step,
    )


def _offer_context_query(job_ids: Sequence[uuid.UUID]) -> Any:
    """Contexto de los jobs de oferta (C-12, D2): oferta → entrada → paciente, por `clinic_id`."""
    return (
        select(
            ReminderJob.id.label("job_id"),
            WaitlistOffer.status.label("offer_status"),
            WaitlistOffer.starts_at,
            WaitlistOffer.expires_at,
            Patient.full_name,
            Patient.phone_e164,
            Patient.email,
            Patient.whatsapp_opt_in,
            Professional.display_name.label("professional_name"),
            Clinic.name.label("clinic_name"),
            Clinic.timezone,
            Clinic.whatsapp_phone_number_id.label("clinic_whatsapp_number"),
            NotificationTemplate.id.label("template_id"),
            NotificationTemplate.meta_template_name,
            NotificationTemplate.body_preview,
            NotificationTemplate.active.label("template_active"),
            _email_consent(WaitingListEntry.patient_id, WaitingListEntry).label("email_consent"),
        )
        .select_from(ReminderJob)
        .join(
            WaitlistOffer,
            and_(
                WaitlistOffer.clinic_id == ReminderJob.clinic_id,
                WaitlistOffer.id == ReminderJob.waitlist_offer_id,
            ),
        )
        .join(
            WaitingListEntry,
            and_(
                WaitingListEntry.clinic_id == WaitlistOffer.clinic_id,
                WaitingListEntry.id == WaitlistOffer.entry_id,
            ),
        )
        .join(
            Patient,
            and_(
                Patient.clinic_id == WaitingListEntry.clinic_id,
                Patient.id == WaitingListEntry.patient_id,
            ),
        )
        .join(
            Professional,
            and_(
                Professional.clinic_id == WaitlistOffer.clinic_id,
                Professional.id == WaitlistOffer.professional_id,
            ),
        )
        .join(Clinic, Clinic.id == ReminderJob.clinic_id)
        .outerjoin(NotificationTemplate, _template_join())
        .where(ReminderJob.id.in_(list(job_ids)))
    )


def _context_query(job_ids: Sequence[uuid.UUID]) -> Any:
    """Contexto de los jobs en UNA consulta, siempre unida por `clinic_id` (regla 4)."""
    email_consent = _email_consent(Appointment.patient_id, Appointment)
    return (
        select(
            ReminderJob.id.label("job_id"),
            Appointment.id.label("appointment_id"),
            Appointment.status.label("appointment_status"),
            Appointment.starts_at,
            Patient.full_name,
            Patient.phone_e164,
            Patient.email,
            Patient.whatsapp_opt_in,
            Professional.display_name.label("professional_name"),
            Clinic.name.label("clinic_name"),
            Clinic.timezone,
            Clinic.whatsapp_phone_number_id.label("clinic_whatsapp_number"),
            NotificationTemplate.id.label("template_id"),
            NotificationTemplate.meta_template_name,
            NotificationTemplate.body_preview,
            NotificationTemplate.active.label("template_active"),
            email_consent.label("email_consent"),
        )
        .select_from(ReminderJob)
        .join(
            Appointment,
            and_(
                Appointment.clinic_id == ReminderJob.clinic_id,
                Appointment.id == ReminderJob.appointment_id,
            ),
        )
        .join(
            Patient,
            and_(Patient.clinic_id == Appointment.clinic_id, Patient.id == Appointment.patient_id),
        )
        .join(
            Professional,
            and_(
                Professional.clinic_id == Appointment.clinic_id,
                Professional.id == Appointment.professional_id,
            ),
        )
        .join(Clinic, Clinic.id == ReminderJob.clinic_id)
        .outerjoin(NotificationTemplate, _template_join())
        .where(ReminderJob.id.in_(list(job_ids)))
    )


def _close(
    session: AsyncSession,
    job: ReminderJob,
    to: ReminderStatus,
    reason: ReminderReason,
    event: DeliveryEventType,
) -> None:
    job.status = to
    job.reason = reason.value
    job.manual_resend_at = None
    add_event(session, job.id, job.clinic_id, event, {"reason": reason.value})


async def _escalate_to_email(
    session: AsyncSession,
    job: ReminderJob,
    *,
    starts_at: datetime,
    patient_email: str | None,
    email_blocked: bool,
    now: datetime,
    stats: TickStats,
) -> None:
    if await escalate_to_email(
        session,
        job,
        starts_at=starts_at,
        patient_email=patient_email,
        email_blocked=email_blocked,
        now=now,
    ):
        stats.escalated += 1


async def _claim_batch(
    factory: SessionFactory,
    enabled: Sequence[ReminderChannel],
    now: datetime,
    settings: Settings,
    stats: TickStats,
) -> Claimed:
    compartido = settings.META_PHONE_NUMBER_ID.strip() or None
    async with factory() as session, session.begin():
        jobs = list(
            (
                await session.execute(
                    select(ReminderJob)
                    .where(
                        ReminderJob.status == ReminderStatus.SCHEDULED,
                        ReminderJob.available_at <= now,
                        ReminderJob.channel.in_(list(enabled)),
                    )
                    .order_by(ReminderJob.available_at, ReminderJob.id)
                    .limit(settings.REMINDER_BATCH_SIZE)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        if not jobs:
            return Claimed(0, [])
        de_turno = [j.id for j in jobs if j.appointment_id is not None]
        de_oferta = [j.id for j in jobs if j.waitlist_offer_id is not None]
        contexto: dict[uuid.UUID, Any] = {}
        if de_turno:
            filas = (await session.execute(_context_query(de_turno))).all()
            contexto |= {fila.job_id: fila for fila in filas}
        if de_oferta:
            filas = (await session.execute(_offer_context_query(de_oferta))).all()
            contexto |= {fila.job_id: fila for fila in filas}
        ready: list[Ready] = []
        for job in jobs:
            ctx = contexto[job.id]
            email = (ctx.email or "").strip() or None
            email_blocked = ctx.email_consent is ConsentStatus.OPT_OUT
            es_oferta = job.waitlist_offer_id is not None
            if es_oferta and (
                ctx.offer_status is not WaitlistOfferStatus.PENDING or now >= ctx.expires_at
            ):
                # C-12: la oferta ya no se puede tomar; no se avisa de algo cerrado.
                _close(
                    session,
                    job,
                    ReminderStatus.CANCELLED,
                    ReminderReason.OFFER_CLOSED,
                    DeliveryEventType.CANCELLED,
                )
                stats.cancelled += 1
            elif not es_oferta and ctx.appointment_status not in _ACTIVE:
                _close(
                    session,
                    job,
                    ReminderStatus.CANCELLED,
                    ReminderReason.APPOINTMENT_INACTIVE,
                    DeliveryEventType.CANCELLED,
                )
                stats.cancelled += 1
            elif not es_oferta and now >= ctx.starts_at:
                _close(
                    session,
                    job,
                    ReminderStatus.SKIPPED,
                    ReminderReason.APPOINTMENT_STARTED,
                    DeliveryEventType.SKIPPED,
                )
                stats.skipped += 1
            elif not es_oferta and ctx.starts_at != job.starts_at_snapshot:
                # Un camino de escritura no reconcilió: se recalcula la secuencia, no se envía.
                turno = await session.get(Appointment, ctx.appointment_id)
                if turno is not None:
                    await session.flush()
                    await reconcile(session, turno, now=now)
                stats.released += 1
            elif job.channel is ReminderChannel.WHATSAPP and not ctx.whatsapp_opt_in:
                _close(
                    session,
                    job,
                    ReminderStatus.SKIPPED,
                    ReminderReason.NO_CONSENT,
                    DeliveryEventType.SKIPPED,
                )
                stats.skipped += 1
            elif job.channel is ReminderChannel.WHATSAPP and not ctx.phone_e164:
                _close(
                    session,
                    job,
                    ReminderStatus.SKIPPED,
                    ReminderReason.NO_RECIPIENT,
                    DeliveryEventType.SKIPPED,
                )
                stats.skipped += 1
            elif job.channel is ReminderChannel.EMAIL and email is None:
                _close(
                    session,
                    job,
                    ReminderStatus.SKIPPED,
                    ReminderReason.NO_RECIPIENT,
                    DeliveryEventType.SKIPPED,
                )
                stats.skipped += 1
            elif job.channel is ReminderChannel.EMAIL and email_blocked:
                _close(
                    session,
                    job,
                    ReminderStatus.SKIPPED,
                    ReminderReason.NO_CONSENT,
                    DeliveryEventType.SKIPPED,
                )
                stats.skipped += 1
            elif ctx.template_id is None or not ctx.template_active:
                _close(
                    session,
                    job,
                    ReminderStatus.FAILED,
                    ReminderReason.TEMPLATE_INACTIVE,
                    DeliveryEventType.FAILED,
                )
                stats.failed += 1
                await session.flush()
                await _escalate_to_email(
                    session,
                    job,
                    starts_at=ctx.starts_at,
                    patient_email=email,
                    email_blocked=email_blocked,
                    now=now,
                    stats=stats,
                )
            else:
                # Las ramas anteriores garantizan el destinatario del canal (teléfono o email).
                recipient = ctx.phone_e164 if job.channel is ReminderChannel.WHATSAPP else email
                assert recipient is not None
                job.status = ReminderStatus.SENDING
                job.claimed_at = now
                job.attempts += 1
                job.template_id = ctx.template_id
                job.reason = None
                ready.append(
                    Ready(
                        job_id=job.id,
                        clinic_id=job.clinic_id,
                        appointment_id=job.appointment_id,
                        channel=job.channel,
                        step=job.step,
                        attempts=job.attempts,
                        starts_at=ctx.starts_at,
                        starts_at_snapshot=job.starts_at_snapshot,
                        template_name=ctx.meta_template_name,
                        body_preview=ctx.body_preview,
                        recipient=recipient,
                        patient_first_name=(ctx.full_name.split() or [""])[0],
                        professional_name=ctx.professional_name,
                        clinic_name=ctx.clinic_name,
                        tz=ZoneInfo(ctx.timezone),
                        patient_email=email,
                        email_blocked=email_blocked,
                        sender_id=ctx.clinic_whatsapp_number or compartido,
                        manual=job.manual_resend_at is not None,
                        waitlist_offer_id=job.waitlist_offer_id,
                        expires_at=ctx.expires_at if es_oferta else None,
                    )
                )
        await session.flush()
    stats.claimed += len(jobs)
    return Claimed(len(jobs), ready)


# ------------------------------------------------------------------------------ envío


def _build_message(ready: Ready, settings: Settings, now: datetime) -> OutboundMessage:
    """Arma el mensaje; lanza `MissingVariable` o `ManageLinkDisabled` (error de configuración)."""
    params = {
        "nombre": ready.patient_first_name,
        "clinica": ready.clinic_name,
        "profesional": ready.professional_name,
        "fecha": format_date(ready.starts_at, ready.tz),
        "hora": format_time(ready.starts_at, ready.tz),
    }
    if ready.waitlist_offer_id is not None and ready.expires_at is not None:
        # C-12 (D2): link de la oferta (nunca el de gestión de un turno) y su vencimiento.
        params["link"] = build_offer_url(settings, ready.waitlist_offer_id)
        params["vence"] = format_time(ready.expires_at, ready.tz)
        asunto = f"Se liberó un turno en {ready.clinic_name}"
    else:
        assert ready.appointment_id is not None
        params["link"] = build_manage_url(settings, ready.appointment_id)
        asunto = f"Recordatorio de tu turno en {ready.clinic_name}"
    # Todo recordatorio proactivo sale como plantilla aunque la ventana de 24 h esté abierta: el
    # texto libre es solo para responder a un entrante (outbox de C-10, D8).
    es_whatsapp = ready.channel is ReminderChannel.WHATSAPP
    return OutboundMessage(
        channel=ready.channel,
        to=ready.recipient,
        template_name=ready.template_name,
        locale="es_AR",
        params=params,
        body=render(ready.body_preview, params),
        subject=asunto if ready.channel is ReminderChannel.EMAIL else None,
        sender_id=ready.sender_id if es_whatsapp else None,
        param_order=param_order_of(ready.body_preview) if es_whatsapp else (),
        buttons=whatsapp_buttons(ready.step) if es_whatsapp else (),
    )


async def _recheck(factory: SessionFactory, ready: Ready, now: datetime) -> bool:
    """Último chequeo justo antes de enviar; devuelve `False` si el job ya no debe salir."""
    if ready.waitlist_offer_id is not None:
        return await _recheck_offer(factory, ready, now)
    async with factory() as session, session.begin():
        fila = (
            await session.execute(
                select(Appointment.status, Appointment.starts_at).where(
                    Appointment.clinic_id == ready.clinic_id,
                    Appointment.id == ready.appointment_id,
                )
            )
        ).one_or_none()
        cerrar: tuple[ReminderStatus, ReminderReason, DeliveryEventType] | None = None
        if fila is None or fila.status not in _ACTIVE:
            cerrar = (
                ReminderStatus.CANCELLED,
                ReminderReason.APPOINTMENT_INACTIVE,
                DeliveryEventType.CANCELLED,
            )
        elif now >= fila.starts_at:
            cerrar = (
                ReminderStatus.SKIPPED,
                ReminderReason.APPOINTMENT_STARTED,
                DeliveryEventType.SKIPPED,
            )
        elif fila.starts_at != ready.starts_at_snapshot:
            # Se movió después del reclamo: el job vuelve a la cola y la secuencia se recalcula.
            await session.execute(
                update(ReminderJob)
                .where(
                    ReminderJob.id == ready.job_id,
                    ReminderJob.clinic_id == ready.clinic_id,
                    ReminderJob.status == ReminderStatus.SENDING,
                )
                .values(
                    status=ReminderStatus.SCHEDULED,
                    claimed_at=None,
                    attempts=ReminderJob.attempts - 1,
                )
                .execution_options(synchronize_session=False)
            )
            turno = await session.get(Appointment, ready.appointment_id)
            if turno is not None:
                await reconcile(session, turno, now=now)
            return False
        if cerrar is None:
            return True
        estado, motivo, evento = cerrar
        cerrado = await session.execute(
            update(ReminderJob)
            .where(
                ReminderJob.id == ready.job_id,
                ReminderJob.clinic_id == ready.clinic_id,
                ReminderJob.status == ReminderStatus.SENDING,
            )
            .values(status=estado, reason=motivo.value, manual_resend_at=None)
            .execution_options(synchronize_session=False)
        )
        if cerrado.rowcount:  # type: ignore[attr-defined]
            add_event(session, ready.job_id, ready.clinic_id, evento, {"reason": motivo.value})
        return False


async def _recheck_offer(factory: SessionFactory, ready: Ready, now: datetime) -> bool:
    """Oferta todavía `pending` y sin vencer (C-12, D2); si no, el job queda `offer_closed`."""
    async with factory() as session, session.begin():
        fila = (
            await session.execute(
                select(WaitlistOffer.status, WaitlistOffer.expires_at).where(
                    WaitlistOffer.clinic_id == ready.clinic_id,
                    WaitlistOffer.id == ready.waitlist_offer_id,
                )
            )
        ).one_or_none()
        if (
            fila is not None
            and fila.status is WaitlistOfferStatus.PENDING
            and now < fila.expires_at
        ):
            return True
        motivo = ReminderReason.OFFER_CLOSED
        cerrado = await session.execute(
            update(ReminderJob)
            .where(
                ReminderJob.id == ready.job_id,
                ReminderJob.clinic_id == ready.clinic_id,
                ReminderJob.status == ReminderStatus.SENDING,
            )
            .values(status=ReminderStatus.CANCELLED, reason=motivo.value, manual_resend_at=None)
            .execution_options(synchronize_session=False)
        )
        if cerrado.rowcount:  # type: ignore[attr-defined]
            add_event(
                session,
                ready.job_id,
                ready.clinic_id,
                DeliveryEventType.CANCELLED,
                {"reason": motivo.value},
            )
        return False


async def _record_success(
    factory: SessionFactory,
    ready: Ready,
    provider_message_id: str,
    settings: Settings,
    now: datetime,
) -> bool:
    async with factory() as session, session.begin():
        actualizado = await session.execute(
            update(ReminderJob)
            .where(
                ReminderJob.id == ready.job_id,
                ReminderJob.clinic_id == ready.clinic_id,
                ReminderJob.status == ReminderStatus.SENDING,
            )
            .values(
                status=ReminderStatus.SENT,
                sent_at=now,
                provider_message_id=provider_message_id,
                cost_micros=_cost(settings, ready.channel),
                last_error=None,
                reason=None,
                manual_resend_at=None,
            )
            .execution_options(synchronize_session=False)
        )
        if not actualizado.rowcount:  # type: ignore[attr-defined]
            return False
        await session.execute(
            insert(DeliveryEvent).values(
                clinic_id=ready.clinic_id,
                reminder_job_id=ready.job_id,
                event_type=DeliveryEventType.SENT,
                # Mismo instante que `sent_at`: el reporte (C-10) filtra el envío por este evento.
                occurred_at=now,
                # El costo va en el evento (C-10, D10): el reporte lo suma sin leer estado mutable.
                payload={
                    "attempt": ready.attempts,
                    "kind": "template",
                    "cost_micros": _cost(settings, ready.channel),
                    **({"manual": True} if ready.manual else {}),
                },
            )
        )
    return True


async def _record_failure(
    factory: SessionFactory,
    ready: Ready,
    code: str,
    retryable: bool,
    settings: Settings,
    now: datetime,
    stats: TickStats,
) -> None:
    final = (not retryable) or ready.attempts >= settings.REMINDER_MAX_ATTEMPTS
    async with factory() as session, session.begin():
        job = (
            await session.execute(
                select(ReminderJob)
                .where(
                    ReminderJob.id == ready.job_id,
                    ReminderJob.clinic_id == ready.clinic_id,
                    ReminderJob.status == ReminderStatus.SENDING,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if job is None:
            return  # otro worker lo recuperó o lo cerró: no se pisa
        job.last_error = code
        detalle: dict[str, Any] = {"attempt": ready.attempts, "code": code}
        if not final:
            espera = _backoff(settings, ready.attempts)
            job.status = ReminderStatus.SCHEDULED
            job.available_at = now + espera
            job.claimed_at = None
            add_event(
                session,
                job.id,
                job.clinic_id,
                DeliveryEventType.ATTEMPT_FAILED,
                {**detalle, "retry_in_min": int(espera.total_seconds() // 60)},
            )
            stats.retried += 1
            return
        add_event(session, job.id, job.clinic_id, DeliveryEventType.ATTEMPT_FAILED, detalle)
        job.status = ReminderStatus.FAILED
        job.manual_resend_at = None
        job.reason = (
            ReminderReason.SEND_FAILED
            if retryable or code in _CONFIG_CODES
            else ReminderReason.PROVIDER_REJECTED
        ).value
        add_event(
            session,
            job.id,
            job.clinic_id,
            DeliveryEventType.FAILED,
            {"reason": job.reason},
        )
        stats.failed += 1
        await session.flush()
        await _escalate_to_email(
            session,
            job,
            starts_at=ready.starts_at,
            patient_email=ready.patient_email,
            email_blocked=ready.email_blocked,
            now=now,
            stats=stats,
        )


# Fallos de configuración del propio motor: no son un rechazo del proveedor.
_CONFIG_CODES = frozenset({"template_variables", "link_disabled"})


async def _deliver(
    factory: SessionFactory,
    senders: Senders,
    settings: Settings,
    clock: Clock,
    ready: Ready,
    stats: TickStats,
    gate: asyncio.Semaphore,
) -> None:
    async with gate:
        if not await _recheck(factory, ready, clock()):
            stats.released += 1
            return
        try:
            mensaje = _build_message(ready, settings, clock())
        except MissingVariable:
            await _record_failure(
                factory, ready, "template_variables", False, settings, clock(), stats
            )
            return
        except ManageLinkDisabled:
            await _record_failure(factory, ready, "link_disabled", False, settings, clock(), stats)
            return
        try:
            resultado = await senders[ready.channel].send(mensaje)
        except SendError as error:
            await _record_failure(
                factory, ready, error.code, error.retryable, settings, clock(), stats
            )
            return
        except Exception as exc:  # noqa: BLE001 — cualquier falla del proveedor es transitoria
            logger.warning("falla inesperada del proveedor (%s)", type(exc).__name__)
            await _record_failure(
                factory, ready, "unexpected_error", True, settings, clock(), stats
            )
            return
        if await _record_success(factory, ready, resultado.provider_message_id, settings, clock()):
            stats.sent += 1


async def _deliver_safe(*args: Any) -> None:
    """Un fallo inesperado de un envío no frena a los demás: el job queda en `sending`.

    El lease lo devuelve a `scheduled` si nadie lo resuelve.
    """
    try:
        await _deliver(*args)
    except Exception as exc:  # noqa: BLE001
        logger.error("error inesperado al despachar un job (%s)", type(exc).__name__)


# ------------------------------------------------------------------------------ tick


async def run_tick(
    factory: SessionFactory, senders: Senders, settings: Settings, *, now: Clock
) -> TickStats:
    """Procesa lo vencido hasta vaciarlo o agotar el presupuesto de tiempo del tick."""
    stats = TickStats()
    await _recover_leases(factory, now(), settings, stats)
    habilitados = list(senders)
    if not habilitados:
        return stats
    # Respuestas de sesión a mensajes entrantes (C-10, D8): mismo worker, mismo canal.
    whatsapp = senders.get(ReminderChannel.WHATSAPP)
    if whatsapp is not None and hasattr(whatsapp, "send_text"):
        await run_replies(factory, whatsapp, settings, now=now)  # type: ignore[arg-type]
    limite = time.monotonic() + settings.REMINDER_TICK_BUDGET_S
    puerta = asyncio.Semaphore(settings.REMINDER_WORKER_CONCURRENCY)
    while time.monotonic() < limite and stats.batches < _MAX_BATCHES:
        lote = await _claim_batch(factory, habilitados, now(), settings, stats)
        if lote.examined == 0:
            break
        stats.batches += 1
        await asyncio.gather(
            *(
                _deliver_safe(factory, senders, settings, now, ready, stats, puerta)
                for ready in lote.ready
            )
        )
    logger.info(
        "tick: lotes=%d reclamados=%d enviados=%d reintentos=%d fallidos=%d saltados=%d "
        "cancelados=%d escalados=%d recuperados=%d",
        stats.batches,
        stats.claimed,
        stats.sent,
        stats.retried,
        stats.failed,
        stats.skipped,
        stats.cancelled,
        stats.escalated,
        stats.recovered,
    )
    return stats
