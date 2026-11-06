"""Outbox de respuestas de sesión de WhatsApp: textos y despacho en el worker (C-10, D8).

Mismo patrón que el despacho de recordatorios de C-09:

1. **Leases**: una respuesta `sending` cuyo reclamo venció vuelve a `pending` (o `failed` si ya
   agotó sus intentos).
2. **Reclamo** en una transacción corta con `FOR UPDATE SKIP LOCKED`: vencida la ventana de 24 h
   del entrante → `expired`; paciente sin opt-in → `skipped` (salvo la confirmación de baja, que
   es la única respuesta que se le manda a quien acaba de darse de baja); sin teléfono →
   `skipped`. Las demás pasan a `sending` con un intento más.
3. **Envío** fuera de la transacción como texto libre (`send_text`) desde el número de la clínica
   (propio o compartido).
4. **Resultado**: `sent`, reintento con el backoff de C-09 o `failed` (sin escalado a email).

Los textos son fijos por tipo, en `es_AR`, y no llevan el nombre del paciente: solo el link de su
propio turno o los datos públicos de la clínica (regla 13). Nada de esto se loguea.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.settings import Settings
from app.models import (
    Clinic,
    Patient,
    WhatsAppOutboundReply,
    WhatsAppReplyKind,
    WhatsAppReplyStatus,
)
from app.modules.reminders.links import ManageLinkDisabled, build_manage_url
from app.modules.reminders.senders.base import SendError, SessionTextSender
from app.modules.reminders.senders.window import WINDOW, choose_message_kind

logger = logging.getLogger("notifications.replies")

SessionFactory = async_sessionmaker[AsyncSession]


@dataclass
class ReplyStats:
    claimed: int = 0
    sent: int = 0
    retried: int = 0
    failed: int = 0
    expired: int = 0
    skipped: int = 0
    recovered: int = 0


@dataclass(frozen=True, slots=True, repr=False)
class _Ready:
    """Respuesta reclamada con lo necesario para enviarla (datos personales: sin `repr`)."""

    reply_id: uuid.UUID
    clinic_id: uuid.UUID
    appointment_id: uuid.UUID | None
    kind: WhatsAppReplyKind
    attempts: int
    to: str
    sender_id: str | None
    clinic_name: str
    clinic_phone: str | None

    def __repr__(self) -> str:
        return f"_Ready(reply={self.reply_id}, kind={self.kind.value})"


def _contacto(clinica: str, telefono: str | None) -> str:
    return f"{clinica} al {telefono}" if telefono else clinica


def render_reply(
    kind: WhatsAppReplyKind,
    *,
    clinic_name: str,
    clinic_phone: str | None,
    manage_url: str | None,
) -> str:
    """Texto de la respuesta; `change_link` exige el link del turno."""
    if kind is WhatsAppReplyKind.CONFIRMED:
        return f"¡Listo! Tu turno en {clinic_name} quedó confirmado. Te esperamos."
    if kind is WhatsAppReplyKind.CHANGE_LINK:
        if manage_url is None:
            raise ManageLinkDisabled("falta el link de gestión")
        return f"Para cambiar o cancelar tu turno en {clinic_name} entrá acá: {manage_url}"
    if kind is WhatsAppReplyKind.CHANGE_CONTACT:
        return (
            "Tu turno ya no se puede cambiar ni cancelar online. "
            f"Comunicate con {_contacto(clinic_name, clinic_phone)}."
        )
    if kind is WhatsAppReplyKind.INACTIVE:
        return (
            "Ese turno ya no está activo. Si necesitás uno nuevo, comunicate con "
            f"{_contacto(clinic_name, clinic_phone)}."
        )
    if kind is WhatsAppReplyKind.AMBIGUOUS:
        return (
            "No pudimos identificar tu turno. Usá el link de tu último recordatorio para "
            "confirmarlo o cambiarlo."
        )
    return (
        "Listo, no te vamos a enviar más mensajes por WhatsApp. Si cambiás de idea, avisale a "
        "tu clínica."
    )


def _backoff(settings: Settings, attempts: int) -> timedelta:
    tramos = settings.reminder_backoff_minutes
    return timedelta(minutes=tramos[min(attempts, len(tramos)) - 1])


async def _recover(
    factory: SessionFactory, now: datetime, settings: Settings, stats: ReplyStats
) -> None:
    limite = now - timedelta(minutes=settings.REMINDER_LEASE_MINUTES)
    vencidas = and_(
        WhatsAppOutboundReply.status == WhatsAppReplyStatus.SENDING,
        WhatsAppOutboundReply.claimed_at < limite,
    )
    async with factory() as session, session.begin():
        agotadas = await session.execute(
            update(WhatsAppOutboundReply)
            .where(vencidas, WhatsAppOutboundReply.attempts >= settings.WHATSAPP_REPLY_MAX_ATTEMPTS)
            .values(status=WhatsAppReplyStatus.FAILED, reason="lease_expired", claimed_at=None)
            .returning(WhatsAppOutboundReply.id)
            .execution_options(synchronize_session=False)
        )
        stats.failed += len(agotadas.all())
        recuperadas = await session.execute(
            update(WhatsAppOutboundReply)
            .where(vencidas)
            .values(status=WhatsAppReplyStatus.PENDING, reason="lease_expired", claimed_at=None)
            .returning(WhatsAppOutboundReply.id)
            .execution_options(synchronize_session=False)
        )
        stats.recovered += len(recuperadas.all())


async def _claim(
    factory: SessionFactory, now: datetime, settings: Settings, stats: ReplyStats
) -> list[_Ready]:
    compartido = settings.META_PHONE_NUMBER_ID.strip() or None
    async with factory() as session, session.begin():
        filas = (
            await session.execute(
                select(
                    WhatsAppOutboundReply,
                    Patient.phone_e164,
                    Patient.whatsapp_opt_in,
                    Clinic.name,
                    Clinic.contact_phone,
                    Clinic.whatsapp_phone_number_id,
                )
                .join(
                    Patient,
                    and_(
                        Patient.clinic_id == WhatsAppOutboundReply.clinic_id,
                        Patient.id == WhatsAppOutboundReply.patient_id,
                    ),
                )
                .join(Clinic, Clinic.id == WhatsAppOutboundReply.clinic_id)
                .where(
                    WhatsAppOutboundReply.status == WhatsAppReplyStatus.PENDING,
                    WhatsAppOutboundReply.available_at <= now,
                )
                .order_by(WhatsAppOutboundReply.available_at, WhatsAppOutboundReply.id)
                .limit(settings.REMINDER_BATCH_SIZE)
                .with_for_update(of=WhatsAppOutboundReply, skip_locked=True)
            )
        ).all()
        listas: list[_Ready] = []
        for respuesta, telefono, opt_in, clinica, contacto, numero in filas:
            stats.claimed += 1
            abierta = choose_message_kind(respuesta.expires_at - WINDOW, now) == "session"
            if not abierta:
                respuesta.status, respuesta.reason = WhatsAppReplyStatus.EXPIRED, "window_closed"
                stats.expired += 1
            elif not opt_in and respuesta.kind is not WhatsAppReplyKind.STOP_ACK:
                respuesta.status, respuesta.reason = WhatsAppReplyStatus.SKIPPED, "no_consent"
                stats.skipped += 1
            elif not telefono:
                respuesta.status, respuesta.reason = WhatsAppReplyStatus.SKIPPED, "no_recipient"
                stats.skipped += 1
            else:
                respuesta.status = WhatsAppReplyStatus.SENDING
                respuesta.claimed_at = now
                respuesta.attempts += 1
                respuesta.reason = None
                listas.append(
                    _Ready(
                        reply_id=respuesta.id,
                        clinic_id=respuesta.clinic_id,
                        appointment_id=respuesta.appointment_id,
                        kind=respuesta.kind,
                        attempts=respuesta.attempts,
                        to=telefono,
                        sender_id=numero or compartido,
                        clinic_name=clinica,
                        clinic_phone=contacto,
                    )
                )
        return listas


async def _result(
    factory: SessionFactory,
    lista: _Ready,
    settings: Settings,
    now: datetime,
    stats: ReplyStats,
    *,
    provider_id: str | None = None,
    error: SendError | None = None,
) -> None:
    async with factory() as session, session.begin():
        respuesta = (
            await session.execute(
                select(WhatsAppOutboundReply)
                .where(
                    WhatsAppOutboundReply.id == lista.reply_id,
                    WhatsAppOutboundReply.clinic_id == lista.clinic_id,
                    WhatsAppOutboundReply.status == WhatsAppReplyStatus.SENDING,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if respuesta is None:
            return  # otro worker la recuperó: no se pisa
        respuesta.claimed_at = None
        if error is None:
            respuesta.status = WhatsAppReplyStatus.SENT
            respuesta.sent_at = now
            respuesta.provider_message_id = provider_id
            respuesta.last_error = None
            stats.sent += 1
            return
        respuesta.last_error = error.code[:64]
        if error.retryable and lista.attempts < settings.WHATSAPP_REPLY_MAX_ATTEMPTS:
            respuesta.status = WhatsAppReplyStatus.PENDING
            respuesta.available_at = now + _backoff(settings, lista.attempts)
            stats.retried += 1
        else:
            respuesta.status = WhatsAppReplyStatus.FAILED
            respuesta.reason = "send_failed"
            stats.failed += 1


async def run_replies(
    factory: SessionFactory,
    sender: SessionTextSender,
    settings: Settings,
    *,
    now: Callable[[], datetime],
) -> ReplyStats:
    """Despacha las respuestas pendientes (un lote por llamada)."""
    stats = ReplyStats()
    await _recover(factory, now(), settings, stats)
    for lista in await _claim(factory, now(), settings, stats):
        try:
            url = (
                build_manage_url(settings, lista.appointment_id)
                if lista.kind is WhatsAppReplyKind.CHANGE_LINK and lista.appointment_id
                else None
            )
            cuerpo = render_reply(
                lista.kind,
                clinic_name=lista.clinic_name,
                clinic_phone=lista.clinic_phone,
                manage_url=url,
            )
        except ManageLinkDisabled:
            await _result(
                factory,
                lista,
                settings,
                now(),
                stats,
                error=SendError("link_disabled", retryable=False),
            )
            continue
        if not lista.sender_id:
            await _result(
                factory,
                lista,
                settings,
                now(),
                stats,
                error=SendError("no_sender_id", retryable=False),
            )
            continue
        try:
            resultado = await sender.send_text(lista.sender_id, lista.to, cuerpo)
        except SendError as error:
            await _result(factory, lista, settings, now(), stats, error=error)
            continue
        except Exception as exc:  # noqa: BLE001 — cualquier falla del proveedor es transitoria
            logger.warning("falla inesperada al responder (%s)", type(exc).__name__)
            await _result(
                factory,
                lista,
                settings,
                now(),
                stats,
                error=SendError("unexpected_error", retryable=True),
            )
            continue
        await _result(
            factory, lista, settings, now(), stats, provider_id=resultado.provider_message_id
        )
    if stats.claimed or stats.recovered:
        logger.info(
            "respuestas: reclamadas=%d enviadas=%d reintentos=%d fallidas=%d vencidas=%d "
            "salteadas=%d recuperadas=%d",
            stats.claimed,
            stats.sent,
            stats.retried,
            stats.failed,
            stats.expired,
            stats.skipped,
            stats.recovered,
        )
    return stats
