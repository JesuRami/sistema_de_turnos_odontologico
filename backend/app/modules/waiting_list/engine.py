"""Motor de la lista de espera: evaluar un hueco, crear la oferta y vencer (C-12, D3/D4).

`evaluate_slot` corre dentro de la transacción del llamador (sin commit): la cancelación de un turno
(RN-CX-03), un rechazo, un retiro o un vencimiento. Busca la primera entrada compatible —primero
las prioritarias, después por antigüedad (FIFO con filtro, RN-LE-02)— con `FOR UPDATE SKIP LOCKED`,
así nunca espera a otra transacción, y crea la oferta, su evento y su envío.

No toma locks de profesional ni sillón: si el hueco se ocupa después, la aceptación lo detecta con
el mismo camino de escritura que recepción (`book`). Ninguna automatización mueve un turno
existente (RN-GL-02).

`run_waitlist_tick` es el cron del worker: vence ofertas, rota el hueco y vence entradas cuyo
período terminó.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, any_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.settings import Settings
from app.models import (
    VIGENT_STATUSES,
    ActorType,
    Appointment,
    Block,
    Clinic,
    Consent,
    ConsentStatus,
    Patient,
    Professional,
    ReminderChannel,
    ReminderJob,
    WaitingListEntry,
    WaitingListStatus,
    WaitlistEventType,
    WaitlistOffer,
    WaitlistOfferStatus,
)
from app.modules.appointments.audit import Actor
from app.modules.reminders.templates import STEP_WAITLIST_OFFER
from app.modules.waiting_list.audit import finish_offer, offer_payload, record_event

logger = logging.getLogger("waiting_list.engine")


@dataclass(frozen=True, slots=True)
class Slot:
    """Un hueco exacto: el de un turno cancelado o el que elige recepción."""

    clinic_id: uuid.UUID
    professional_id: uuid.UUID
    chair_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
    source_appointment_id: uuid.UUID | None = None

    @classmethod
    def of_offer(cls, offer: WaitlistOffer) -> Slot:
        return cls(
            offer.clinic_id,
            offer.professional_id,
            offer.chair_id,
            offer.starts_at,
            offer.ends_at,
            offer.source_appointment_id,
        )

    @classmethod
    def of_appointment(cls, appointment: Appointment) -> Slot:
        return cls(
            appointment.clinic_id,
            appointment.professional_id,
            appointment.chair_id,
            appointment.starts_at,
            appointment.ends_at,
            appointment.id,
        )


def system_actor(clinic_id: uuid.UUID) -> Actor:
    return Actor(clinic_id=clinic_id, type=ActorType.SYSTEM)


# ------------------------------------------------------------------------- hueco


async def clinic_offer_policy(
    session: AsyncSession, clinic_id: uuid.UUID
) -> tuple[ZoneInfo, timedelta]:
    fila = (
        await session.execute(
            select(Clinic.timezone, Clinic.waitlist_offer_ttl_hours).where(Clinic.id == clinic_id)
        )
    ).one()
    return ZoneInfo(fila.timezone), timedelta(hours=fila.waitlist_offer_ttl_hours)


def auto_expiry(
    slot: Slot, *, now: datetime, ttl: timedelta, settings: Settings
) -> datetime | None:
    """`min(now + ttl, inicio − lead)`; `None` si la ventana queda por debajo del mínimo (D3)."""
    vence = min(now + ttl, slot.starts_at - timedelta(minutes=settings.WAITLIST_MIN_LEAD_MINUTES))
    if vence - now < timedelta(minutes=settings.WAITLIST_MIN_OFFER_WINDOW_MINUTES):
        return None
    return vence


async def slot_is_free(session: AsyncSession, slot: Slot) -> bool:
    """Sin turnos vigentes (con el buffer del profesional) ni bloqueos sobre el hueco."""
    buffer_min = await session.scalar(
        select(Professional.buffer_min).where(
            Professional.clinic_id == slot.clinic_id, Professional.id == slot.professional_id
        )
    )
    ocupado_hasta = slot.ends_at + timedelta(minutes=buffer_min or 0)
    choque = await session.scalar(
        select(
            exists().where(
                Appointment.clinic_id == slot.clinic_id,
                or_(
                    Appointment.professional_id == slot.professional_id,
                    Appointment.chair_id == slot.chair_id,
                ),
                Appointment.status.in_(VIGENT_STATUSES),
                Appointment.starts_at < ocupado_hasta,
                Appointment.occupied_until > slot.starts_at,
            )
        )
    )
    if choque:
        return False
    bloqueo = await session.scalar(
        select(
            exists().where(
                Block.clinic_id == slot.clinic_id,
                Block.removed_at.is_(None),
                or_(Block.professional_id == slot.professional_id, Block.chair_id == slot.chair_id),
                Block.starts_at < slot.ends_at,
                Block.ends_at > slot.starts_at,
            )
        )
    )
    return not bloqueo


# ---------------------------------------------------------------------- candidatas


def _email_consent(patient_id: Any) -> Any:
    return (
        select(Consent.status)
        .where(
            Consent.clinic_id == WaitingListEntry.clinic_id,
            Consent.patient_id == patient_id,
            Consent.channel == ReminderChannel.EMAIL,
        )
        .order_by(Consent.changed_at.desc(), Consent.id)
        .limit(1)
        .correlate(WaitingListEntry)
        .scalar_subquery()
    )


def reachable_sql() -> Any:
    """El paciente tiene un canal utilizable: WhatsApp con opt-in y teléfono, o email sin baja."""
    return or_(
        and_(Patient.phone_e164.is_not(None), Patient.whatsapp_opt_in.is_(True)),
        and_(
            Patient.email.is_not(None),
            Patient.email != "",
            or_(
                _email_consent(Patient.id).is_(None),
                _email_consent(Patient.id) != ConsentStatus.OPT_OUT,
            ),
        ),
    )


def patient_busy_sql(slot: Slot, patient_id: Any) -> Any:
    """Turno vigente del paciente que se superpone con el hueco."""
    return exists().where(
        Appointment.clinic_id == slot.clinic_id,
        Appointment.patient_id == patient_id,
        Appointment.status.in_(VIGENT_STATUSES),
        Appointment.starts_at < slot.ends_at,
        Appointment.ends_at > slot.starts_at,
    )


def candidates_stmt(slot: Slot, tz: ZoneInfo) -> Any:
    """Entradas compatibles con el hueco, en el orden de la cola (D3).

    La fecha, la hora y el día local del hueco se calculan con la zona de la clínica; el hueco
    tiene que caer completo dentro de la franja.
    """
    inicio = slot.starts_at.astimezone(tz)
    fin = slot.ends_at.astimezone(tz)
    dia: date = inicio.date()
    hora_inicio: time = inicio.time()
    hora_fin: time = fin.time() if fin.date() == dia else time.max
    E = WaitingListEntry
    ya_ofrecido = exists().where(
        WaitlistOffer.clinic_id == E.clinic_id,
        WaitlistOffer.entry_id == E.id,
        WaitlistOffer.professional_id == slot.professional_id,
        WaitlistOffer.chair_id == slot.chair_id,
        WaitlistOffer.starts_at == slot.starts_at,
    )
    return (
        select(E)
        .join(Patient, and_(Patient.clinic_id == E.clinic_id, Patient.id == E.patient_id))
        .where(
            E.clinic_id == slot.clinic_id,
            E.status == WaitingListStatus.WAITING,
            or_(E.professional_id.is_(None), E.professional_id == slot.professional_id),
            E.date_from <= dia,
            E.date_to >= dia,
            or_(E.time_from.is_(None), and_(E.time_from <= hora_inicio, E.time_to >= hora_fin)),
            or_(E.weekdays.is_(None), any_(E.weekdays) == inicio.weekday()),
            Patient.archived_at.is_(None),
            Patient.merged_into_patient_id.is_(None),
            reachable_sql(),
            ~patient_busy_sql(slot, E.patient_id),
            ~ya_ofrecido,
        )
        .order_by(E.prioritized_at.asc().nulls_last(), E.created_at, E.id)
    )


async def _channel(session: AsyncSession, entry: WaitingListEntry) -> ReminderChannel | None:
    fila = (
        await session.execute(
            select(Patient.phone_e164, Patient.whatsapp_opt_in, Patient.email).where(
                Patient.clinic_id == entry.clinic_id, Patient.id == entry.patient_id
            )
        )
    ).one()
    if fila.phone_e164 and fila.whatsapp_opt_in:
        return ReminderChannel.WHATSAPP
    if fila.email and fila.email.strip():
        baja = await session.scalar(
            select(Consent.status)
            .where(
                Consent.clinic_id == entry.clinic_id,
                Consent.patient_id == entry.patient_id,
                Consent.channel == ReminderChannel.EMAIL,
            )
            .order_by(Consent.changed_at.desc(), Consent.id)
            .limit(1)
        )
        if baja is not ConsentStatus.OPT_OUT:
            return ReminderChannel.EMAIL
    return None


# ------------------------------------------------------------------------- oferta


async def create_offer(
    session: AsyncSession,
    actor: Actor,
    entry: WaitingListEntry,
    slot: Slot,
    *,
    expires_at: datetime,
    now: datetime,
    mode: str,
    extra: dict[str, Any] | None = None,
) -> WaitlistOffer:
    """Oferta `pending`, entrada `offered`, evento y envío inmediato por el motor (D2)."""
    offer = WaitlistOffer(
        clinic_id=entry.clinic_id,
        entry_id=entry.id,
        professional_id=slot.professional_id,
        chair_id=slot.chair_id,
        starts_at=slot.starts_at,
        ends_at=slot.ends_at,
        expires_at=expires_at,
        status=WaitlistOfferStatus.PENDING,
        mode=mode,
        source_appointment_id=slot.source_appointment_id,
        created_by_user_id=actor.user_id,
    )
    session.add(offer)
    entry.status = WaitingListStatus.OFFERED
    await session.flush()
    canal = await _channel(session, entry)
    if canal is not None:
        session.add(
            ReminderJob(
                clinic_id=entry.clinic_id,
                waitlist_offer_id=offer.id,
                step=STEP_WAITLIST_OFFER,
                channel=canal,
                scheduled_for=now,
                available_at=now,
                starts_at_snapshot=slot.starts_at,
            )
        )
        await session.flush()
    await record_event(
        session,
        actor,
        clinic_id=entry.clinic_id,
        entry_id=entry.id,
        event=WaitlistEventType.OFFER_CREATED,
        offer_id=offer.id,
        payload={
            **offer_payload(offer),
            "expires_at": expires_at,
            "source_appointment_id": slot.source_appointment_id,
            "channel": canal.value if canal else None,
            **(extra or {}),
        },
    )
    return offer


async def evaluate_slot(
    session: AsyncSession,
    slot: Slot,
    *,
    now: datetime,
    settings: Settings,
    actor: Actor | None = None,
) -> WaitlistOffer | None:
    """Ofrece el hueco a la primera entrada compatible, si el hueco sigue ofrecible (D3)."""
    tz, ttl = await clinic_offer_policy(session, slot.clinic_id)
    vence = auto_expiry(slot, now=now, ttl=ttl, settings=settings)
    if vence is None or not await slot_is_free(session, slot):
        return None
    entry: WaitingListEntry | None = await session.scalar(
        candidates_stmt(slot, tz).limit(1).with_for_update(of=WaitingListEntry, skip_locked=True)
    )
    if entry is None:
        return None
    return await create_offer(
        session,
        actor or system_actor(slot.clinic_id),
        entry,
        slot,
        expires_at=vence,
        now=now,
        mode="auto",
    )


async def evaluate_cancelled(
    session: AsyncSession, appointment: Appointment, *, now: datetime, settings: Settings
) -> None:
    """Gancho de la cancelación (RN-CX-03): solo turnos que todavía no empezaron."""
    if appointment.starts_at <= now:
        return
    await evaluate_slot(session, Slot.of_appointment(appointment), now=now, settings=settings)


# -------------------------------------------------------------------------- tick


@dataclass
class WaitlistTickStats:
    expired_offers: int = 0
    expired_entries: int = 0
    rotated: int = 0


async def expire_offer(
    session: AsyncSession, offer: WaitlistOffer, *, now: datetime, settings: Settings
) -> bool:
    """Vence una oferta lockeada y rota el hueco; devuelve si se creó otra oferta."""
    actor = system_actor(offer.clinic_id)
    entry = (
        await session.execute(
            select(WaitingListEntry)
            .where(
                WaitingListEntry.clinic_id == offer.clinic_id,
                WaitingListEntry.id == offer.entry_id,
            )
            .with_for_update()
        )
    ).scalar_one()
    await finish_offer(
        session,
        actor,
        offer,
        status=WaitlistOfferStatus.EXPIRED,
        event=WaitlistEventType.OFFER_EXPIRED,
        now=now,
    )
    entry.consecutive_expired += 1
    if entry.consecutive_expired >= settings.WAITLIST_MAX_CONSECUTIVE_EXPIRED:
        entry.status = WaitingListStatus.EXPIRED
        entry.closed_reason = "no_response"
        await session.flush()
        await record_event(
            session,
            actor,
            clinic_id=entry.clinic_id,
            entry_id=entry.id,
            event=WaitlistEventType.ENTRY_EXPIRED,
            payload={"reason": "no_response", "consecutive_expired": entry.consecutive_expired},
        )
    else:
        entry.status = WaitingListStatus.WAITING
        await session.flush()
    return (
        await evaluate_slot(session, Slot.of_offer(offer), now=now, settings=settings) is not None
    )


async def _expire_offers(
    factory: async_sessionmaker[AsyncSession],
    now: datetime,
    settings: Settings,
    stats: WaitlistTickStats,
) -> int:
    async with factory() as session, session.begin():
        ofertas = list(
            (
                await session.execute(
                    select(WaitlistOffer)
                    .where(
                        WaitlistOffer.status == WaitlistOfferStatus.PENDING,
                        WaitlistOffer.expires_at <= now,
                    )
                    .order_by(WaitlistOffer.expires_at, WaitlistOffer.id)
                    .limit(settings.WAITLIST_TICK_BATCH_SIZE)
                    .with_for_update(skip_locked=True)
                )
            ).scalars()
        )
        for offer in ofertas:
            if await expire_offer(session, offer, now=now, settings=settings):
                stats.rotated += 1
        stats.expired_offers += len(ofertas)
    return len(ofertas)


async def _expire_entries(
    factory: async_sessionmaker[AsyncSession],
    now: datetime,
    settings: Settings,
    stats: WaitlistTickStats,
) -> int:
    """Entradas `waiting` cuyo `date_to` ya pasó en la zona de su clínica (`range_elapsed`)."""
    async with factory() as session, session.begin():
        filas = (
            await session.execute(
                select(WaitingListEntry, Clinic.timezone)
                .join(Clinic, Clinic.id == WaitingListEntry.clinic_id)
                .where(
                    WaitingListEntry.status == WaitingListStatus.WAITING,
                    # Prefiltro barato (ningún huso supera ±14 h); la fecha local se mira abajo.
                    WaitingListEntry.date_to < (now + timedelta(days=1)).date(),
                )
                .order_by(WaitingListEntry.date_to, WaitingListEntry.id)
                .limit(settings.WAITLIST_TICK_BATCH_SIZE)
                .with_for_update(of=WaitingListEntry, skip_locked=True)
            )
        ).all()
        vencidas = 0
        for entry, zona in filas:
            if entry.date_to >= now.astimezone(ZoneInfo(zona)).date():
                continue
            entry.status = WaitingListStatus.EXPIRED
            entry.closed_reason = "range_elapsed"
            await session.flush()
            await record_event(
                session,
                system_actor(entry.clinic_id),
                clinic_id=entry.clinic_id,
                entry_id=entry.id,
                event=WaitlistEventType.ENTRY_EXPIRED,
                payload={"reason": "range_elapsed"},
            )
            vencidas += 1
        stats.expired_entries += vencidas
    # Solo se sigue si el lote entero venció: filas del día local todavía vigente no cuentan.
    return vencidas


async def run_waitlist_tick(
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    now: Callable[[], datetime],
    max_batches: int = 100,
) -> WaitlistTickStats:
    """Un tick: vence ofertas (y rota) y vence entradas, por lotes cortos."""
    stats = WaitlistTickStats()
    for _ in range(max_batches):
        if (
            await _expire_offers(factory, now(), settings, stats)
            < settings.WAITLIST_TICK_BATCH_SIZE
        ):
            break
    for _ in range(max_batches):
        if (
            await _expire_entries(factory, now(), settings, stats)
            < settings.WAITLIST_TICK_BATCH_SIZE
        ):
            break
    logger.info(
        "waitlist tick: ofertas_vencidas=%d entradas_vencidas=%d rotadas=%d",
        stats.expired_offers,
        stats.expired_entries,
        stats.rotated,
    )
    return stats
