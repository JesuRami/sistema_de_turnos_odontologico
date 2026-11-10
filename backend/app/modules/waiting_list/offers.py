"""Ofertas de la lista de espera: aceptar, rechazar, retirar y ofrecer a mano (C-12, D5/D10).

Único escritor de las respuestas a una oferta; lo usan el link público (paciente), el panel de
recepción y el webhook de WhatsApp. Orden de locks: oferta → entrada → (al aceptar) profesional →
sillón dentro de `AppointmentsService.book`. Las ofertas hermanas del mismo hueco se cierran con
`SKIP LOCKED`: si otra transacción tiene una, es una aceptación en curso que va a perder la carrera
por su cuenta.

Aceptar es exactamente un alta de agenda (`book`, origen `waitlist`, RN-LE-05): mismas reglas,
mismo EXCLUDE y mismos recordatorios. Si el hueco ya no está, la oferta se cierra, la entrada queda
prioritaria (`slot_lost`) y eso se confirma ANTES de responder el `409`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import DomainError
from app.common.free_text import clean_free_text
from app.common.pagination import decode_cursor, encode_cursor
from app.core.settings import Settings
from app.models import (
    VIGENT_STATUSES,
    Appointment,
    AppointmentOrigin,
    Block,
    Chair,
    Professional,
    ScheduleRule,
    WaitingListEntry,
    WaitingListStatus,
    WaitlistEventType,
    WaitlistOffer,
    WaitlistOfferStatus,
)
from app.models.waiting_list import REASON_MAX_LENGTH
from app.modules.agenda.availability import RuleWindow
from app.modules.appointments.audit import Actor
from app.modules.appointments.service import AppointmentsService, Booking
from app.modules.booking_public.availability import ChairRules, Scoped, public_slots
from app.modules.waiting_list.audit import close_pending_offer, finish_offer, record_event
from app.modules.waiting_list.engine import (
    Slot,
    candidates_stmt,
    clinic_offer_policy,
    create_offer,
    evaluate_slot,
    patient_busy_sql,
    slot_is_free,
)
from app.modules.waiting_list.schemas import (
    AcceptedOffer,
    ManualOfferCreate,
    OfferPage,
    OfferRead,
    SlotCandidate,
    SlotList,
)

FIFO_REASON_MIN = 10
SLOTS_MAX_RANGE = timedelta(days=14)
_SLOT_LOST = frozenset({"slot_taken", "slot_blocked", "outside_schedule", "resource_inactive"})
SLOT_LOST_REASON = "slot_lost"


def _public_alternatives(error: DomainError) -> list[dict[str, str]]:
    """Hasta 3 alternativos del `409` de `book`, solo con inicio y fin (sin ids internos)."""
    crudos = (error.extra or {}).get("alternatives") or []
    return [{"starts_at": a["starts_at"], "ends_at": a["ends_at"]} for a in crudos[:3]]


class OffersService:
    """Casos de uso de ofertas para un actor de la clínica y un instante dados."""

    def __init__(self, session: AsyncSession, actor: Actor, now: datetime, settings: Settings):
        self.session = session
        self.actor = actor
        self.now = now
        self.settings = settings

    # ------------------------------------------------------------------- lectura

    async def locked_offer(self, offer_id: uuid.UUID) -> WaitlistOffer:
        offer: WaitlistOffer | None = (
            await self.session.execute(
                select(WaitlistOffer)
                .where(
                    WaitlistOffer.clinic_id == self.actor.clinic_id,
                    WaitlistOffer.id == offer_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if offer is None:
            raise DomainError(404, "not_found")
        return offer

    async def _locked_entry(self, offer: WaitlistOffer) -> WaitingListEntry:
        entry: WaitingListEntry = (
            await self.session.execute(
                select(WaitingListEntry)
                .where(
                    WaitingListEntry.clinic_id == offer.clinic_id,
                    WaitingListEntry.id == offer.entry_id,
                )
                .with_for_update()
            )
        ).scalar_one()
        return entry

    def _assert_open(self, offer: WaitlistOffer) -> None:
        if offer.status is not WaitlistOfferStatus.PENDING:
            raise DomainError(409, "offer_closed")
        if self.now >= offer.expires_at:
            raise DomainError(409, "offer_expired")

    # ------------------------------------------------------------------- aceptar

    async def accept(self, offer_id: uuid.UUID, *, commit: bool = True) -> AcceptedOffer:
        """`commit=False` (webhook de WhatsApp): todo queda en la transacción del llamador, incluido
        el cierre por hueco perdido antes de lanzar el `409`."""
        offer = await self.locked_offer(offer_id)
        if offer.status is WaitlistOfferStatus.ACCEPTED and offer.appointment_id is not None:
            # Doble clic: misma respuesta, sin otro turno (idempotente).
            return await self._accepted(offer)
        self._assert_open(offer)
        entry = await self._locked_entry(offer)
        slot = Slot.of_offer(offer)
        ocupado = await self.session.scalar(select(patient_busy_sql(slot, entry.patient_id)))
        if ocupado:
            raise DomainError(409, "patient_busy")
        servicio = AppointmentsService(self.session, self.actor, self.now)
        try:
            async with self.session.begin_nested():
                turno = await servicio.book(
                    Booking(
                        patient_id=entry.patient_id,
                        professional_id=offer.professional_id,
                        chair_id=offer.chair_id,
                        starts_at=offer.starts_at,
                        duration_min=int((offer.ends_at - offer.starts_at).total_seconds() // 60),
                    ),
                    origin=AppointmentOrigin.WAITLIST,
                    event_extra={"waitlist_offer_id": offer.id},
                )
        except DomainError as error:
            if error.detail not in _SLOT_LOST:
                raise
            await self._slot_lost(offer, entry, error.detail)
            if commit:
                await self.session.commit()
            raise DomainError(
                409, "slot_taken", extra={"alternatives": _public_alternatives(error)}
            ) from None
        offer.appointment_id = turno.id
        await finish_offer(
            self.session,
            self.actor,
            offer,
            status=WaitlistOfferStatus.ACCEPTED,
            event=WaitlistEventType.OFFER_ACCEPTED,
            now=self.now,
            responded=True,
            extra={"appointment_id": turno.id},
        )
        entry.status = WaitingListStatus.CONVERTED
        entry.closed_reason = "converted"
        entry.consecutive_expired = 0
        await self.session.flush()
        await record_event(
            self.session,
            self.actor,
            clinic_id=entry.clinic_id,
            entry_id=entry.id,
            event=WaitlistEventType.ENTRY_CONVERTED,
            offer_id=offer.id,
            payload={"appointment_id": turno.id},
        )
        await self._close_siblings(offer)
        if commit:
            await self.session.commit()
        return await self._accepted(offer)

    async def _accepted(self, offer: WaitlistOffer) -> AcceptedOffer:
        turno = (
            await self.session.execute(
                select(Appointment.id, Appointment.starts_at, Appointment.ends_at).where(
                    Appointment.clinic_id == offer.clinic_id,
                    Appointment.id == offer.appointment_id,
                )
            )
        ).one()
        return AcceptedOffer(
            offer=OfferRead.model_validate(offer),
            appointment_id=turno.id,
            starts_at=turno.starts_at,
            ends_at=turno.ends_at,
        )

    async def _slot_lost(self, offer: WaitlistOffer, entry: WaitingListEntry, codigo: str) -> None:
        """Perdió la carrera: oferta cerrada y entrada de vuelta a la cola como prioritaria."""
        motivo = "slot_taken" if codigo == "slot_taken" else "slot_unavailable"
        await close_pending_offer(self.session, self.actor, offer, reason=motivo, now=self.now)
        entry.status = WaitingListStatus.WAITING
        entry.prioritized_at = self.now
        entry.priority_reason = SLOT_LOST_REASON
        await self.session.flush()
        await record_event(
            self.session,
            self.actor,
            clinic_id=entry.clinic_id,
            entry_id=entry.id,
            event=WaitlistEventType.ENTRY_PRIORITIZED,
            offer_id=offer.id,
            payload={"reason": SLOT_LOST_REASON},
        )

    async def _close_siblings(self, offer: WaitlistOffer) -> None:
        """Ofertas pendientes de otras entradas para el mismo hueco: `cancelled (slot_taken)`."""
        hermanas = list(
            (
                await self.session.execute(
                    select(WaitlistOffer)
                    .where(
                        WaitlistOffer.clinic_id == offer.clinic_id,
                        WaitlistOffer.id != offer.id,
                        WaitlistOffer.status == WaitlistOfferStatus.PENDING,
                        WaitlistOffer.professional_id == offer.professional_id,
                        WaitlistOffer.chair_id == offer.chair_id,
                        WaitlistOffer.starts_at == offer.starts_at,
                    )
                    .with_for_update(skip_locked=True)
                )
            ).scalars()
        )
        for hermana in hermanas:
            await close_pending_offer(
                self.session, self.actor, hermana, reason="slot_taken", now=self.now
            )
            otra = await self._locked_entry(hermana)
            if otra.status is WaitingListStatus.OFFERED:
                otra.status = WaitingListStatus.WAITING
        await self.session.flush()

    # ------------------------------------------------------------------ rechazar

    async def decline(
        self, offer_id: uuid.UUID, *, leave_list: bool = False, commit: bool = True
    ) -> OfferRead:
        offer = await self.locked_offer(offer_id)
        self._assert_open(offer)
        entry = await self._locked_entry(offer)
        await finish_offer(
            self.session,
            self.actor,
            offer,
            status=WaitlistOfferStatus.DECLINED,
            event=WaitlistEventType.OFFER_DECLINED,
            now=self.now,
            responded=True,
            extra={"leave_list": leave_list},
        )
        entry.consecutive_expired = 0
        if leave_list:
            entry.status = WaitingListStatus.WITHDRAWN
            entry.closed_reason = "withdrawn_by_patient"
            await self.session.flush()
            await record_event(
                self.session,
                self.actor,
                clinic_id=entry.clinic_id,
                entry_id=entry.id,
                event=WaitlistEventType.ENTRY_WITHDRAWN,
                payload={"reason": "withdrawn_by_patient"},
            )
        else:
            entry.status = WaitingListStatus.WAITING
            await self.session.flush()
        await evaluate_slot(
            self.session, Slot.of_offer(offer), now=self.now, settings=self.settings
        )
        if commit:
            await self.session.commit()
        return OfferRead.model_validate(offer)

    # ------------------------------------------------------------------- retirar

    async def withdraw(self, offer_id: uuid.UUID) -> OfferRead:
        """Recepción retira una oferta pendiente: la entrada vuelve a la cola y el hueco rota."""
        offer = await self.locked_offer(offer_id)
        if offer.status is not WaitlistOfferStatus.PENDING:
            raise DomainError(409, "offer_closed")
        entry = await self._locked_entry(offer)
        await close_pending_offer(
            self.session, self.actor, offer, reason="withdrawn_by_staff", now=self.now
        )
        entry.status = WaitingListStatus.WAITING
        await self.session.flush()
        await evaluate_slot(
            self.session, Slot.of_offer(offer), now=self.now, settings=self.settings
        )
        await self.session.commit()
        return OfferRead.model_validate(offer)

    # ------------------------------------------------------------- oferta manual

    async def _rule_for(
        self, professional_id: uuid.UUID, chair_id: uuid.UUID, starts_at: datetime, tz: ZoneInfo
    ) -> ScheduleRule:
        local = starts_at.astimezone(tz)
        reglas = (
            await self.session.execute(
                select(ScheduleRule).where(
                    ScheduleRule.clinic_id == self.actor.clinic_id,
                    ScheduleRule.professional_id == professional_id,
                    ScheduleRule.chair_id == chair_id,
                    ScheduleRule.active.is_(True),
                )
            )
        ).scalars()
        for regla in reglas:
            ventana = RuleWindow(
                weekday=regla.weekday,
                start_time=regla.start_time,
                end_time=regla.end_time,
                slot_duration_min=regla.slot_duration_min,
                valid_from=regla.valid_from,
                valid_to=regla.valid_to,
            )
            if ventana.applies_to(local.date()) and regla.start_time <= local.time():
                fin = (starts_at + timedelta(minutes=regla.slot_duration_min)).astimezone(tz)
                if fin.date() == local.date() and fin.time() <= regla.end_time:
                    return regla
        raise DomainError(422, "outside_schedule")

    async def manual_offer(self, entry_id: uuid.UUID, payload: ManualOfferCreate) -> OfferRead:
        tz, ttl = await clinic_offer_policy(self.session, self.actor.clinic_id)
        if payload.starts_at <= self.now:
            raise DomainError(422, "appointment_in_past")
        prof_activo = await self.session.scalar(
            select(Professional.active).where(
                Professional.clinic_id == self.actor.clinic_id,
                Professional.id == payload.professional_id,
            )
        )
        sillon_activo = await self.session.scalar(
            select(Chair.active).where(
                Chair.clinic_id == self.actor.clinic_id, Chair.id == payload.chair_id
            )
        )
        if prof_activo is None or sillon_activo is None:
            raise DomainError(422, "invalid_resource")
        if not (prof_activo and sillon_activo):
            raise DomainError(409, "resource_inactive")
        regla = await self._rule_for(
            payload.professional_id, payload.chair_id, payload.starts_at, tz
        )
        slot = Slot(
            self.actor.clinic_id,
            payload.professional_id,
            payload.chair_id,
            payload.starts_at,
            payload.starts_at + timedelta(minutes=regla.slot_duration_min),
        )
        entry: WaitingListEntry | None = (
            await self.session.execute(
                select(WaitingListEntry)
                .where(
                    WaitingListEntry.clinic_id == self.actor.clinic_id,
                    WaitingListEntry.id == entry_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if entry is None:
            raise DomainError(404, "not_found")
        if entry.status is WaitingListStatus.OFFERED:
            raise DomainError(409, "entry_offered")
        if entry.status is not WaitingListStatus.WAITING:
            raise DomainError(409, "entry_closed")
        if not await slot_is_free(self.session, slot):
            raise DomainError(409, "slot_taken")
        primera = await self.session.scalar(candidates_stmt(slot, tz).limit(1))
        motivo: str | None = None
        saltea = primera is not None and primera.id != entry.id
        if saltea:
            motivo = clean_free_text(
                payload.fifo_skip_reason,
                max_length=REASON_MAX_LENGTH,
                min_length=FIFO_REASON_MIN,
                code="fifo_skip_reason_required",
            )
        lead = timedelta(minutes=self.settings.WAITLIST_MIN_LEAD_MINUTES)
        vence = min(self.now + ttl, slot.starts_at - lead)
        if vence <= self.now:
            vence = min(self.now + ttl, slot.starts_at)
        offer = await create_offer(
            self.session,
            self.actor,
            entry,
            slot,
            expires_at=vence,
            now=self.now,
            mode="manual",
            extra={"fifo_skip": saltea, **({"fifo_skip_reason": motivo} if motivo else {})},
        )
        await self.session.commit()
        return OfferRead.model_validate(offer)

    async def slots(self, entry_id: uuid.UUID, desde: datetime, hasta: datetime) -> SlotList:
        """Huecos libres de `[desde, hasta)` (≤ 14 días) que respetan las preferencias."""
        if hasta <= desde:
            raise DomainError(422, "invalid_range")
        if hasta - desde > SLOTS_MAX_RANGE:
            raise DomainError(422, "range_too_large")
        tz, _ = await clinic_offer_policy(self.session, self.actor.clinic_id)
        entry: WaitingListEntry | None = await self.session.scalar(
            select(WaitingListEntry).where(
                WaitingListEntry.clinic_id == self.actor.clinic_id,
                WaitingListEntry.id == entry_id,
            )
        )
        if entry is None:
            raise DomainError(404, "not_found")
        stmt = (
            select(ScheduleRule, Professional.buffer_min)
            .join(
                Professional,
                and_(
                    Professional.clinic_id == ScheduleRule.clinic_id,
                    Professional.id == ScheduleRule.professional_id,
                ),
            )
            .join(
                Chair,
                and_(Chair.clinic_id == ScheduleRule.clinic_id, Chair.id == ScheduleRule.chair_id),
            )
            .where(
                ScheduleRule.clinic_id == self.actor.clinic_id,
                ScheduleRule.active.is_(True),
                Professional.active.is_(True),
                Chair.active.is_(True),
            )
        )
        if entry.professional_id is not None:
            stmt = stmt.where(ScheduleRule.professional_id == entry.professional_id)
        grupos: dict[tuple[uuid.UUID, uuid.UUID], tuple[list[RuleWindow], int]] = {}
        for regla, buffer_min in await self.session.execute(stmt):
            ventanas, _ = grupos.setdefault(
                (regla.professional_id, regla.chair_id), ([], buffer_min)
            )
            ventanas.append(
                RuleWindow(
                    weekday=regla.weekday,
                    start_time=regla.start_time,
                    end_time=regla.end_time,
                    slot_duration_min=regla.slot_duration_min,
                    valid_from=regla.valid_from,
                    valid_to=regla.valid_to,
                )
            )
        items: list[SlotCandidate] = []
        for (profesional, sillon), (ventanas, buffer_min) in sorted(grupos.items()):
            ocupados = await self._busy(profesional, sillon, desde, hasta)
            bloqueos = await self._blocks(profesional, sillon, desde, hasta)
            for hueco in public_slots(
                [ChairRules(chair_id=sillon, rules=tuple(ventanas))],
                blocks=bloqueos,
                busy=ocupados,
                desde=desde,
                hasta=hasta,
                tz=tz,
                buffer=timedelta(minutes=buffer_min),
                now=self.now,
                cap=500,
            ):
                if _matches(entry, hueco.starts_at, hueco.ends_at, tz):
                    items.append(
                        SlotCandidate(
                            professional_id=profesional,
                            chair_id=sillon,
                            starts_at=hueco.starts_at,
                            ends_at=hueco.ends_at,
                        )
                    )
        items.sort(key=lambda s: (s.starts_at, str(s.professional_id), str(s.chair_id)))
        return SlotList(timezone=tz.key, items=items)

    async def _busy(
        self, profesional: uuid.UUID, sillon: uuid.UUID, desde: datetime, hasta: datetime
    ) -> list[Scoped]:
        filas = await self.session.execute(
            select(
                Appointment.professional_id,
                Appointment.chair_id,
                Appointment.starts_at,
                Appointment.occupied_until,
            ).where(
                Appointment.clinic_id == self.actor.clinic_id,
                or_(Appointment.professional_id == profesional, Appointment.chair_id == sillon),
                Appointment.status.in_(VIGENT_STATUSES),
                Appointment.starts_at < hasta + timedelta(days=1),
                Appointment.occupied_until > desde,
            )
        )
        return [
            Scoped(
                None if f.professional_id == profesional else f.chair_id,
                f.starts_at,
                f.occupied_until,
            )
            for f in filas
        ]

    async def _blocks(
        self, profesional: uuid.UUID, sillon: uuid.UUID, desde: datetime, hasta: datetime
    ) -> list[Scoped]:
        filas = await self.session.execute(
            select(Block.professional_id, Block.chair_id, Block.starts_at, Block.ends_at).where(
                Block.clinic_id == self.actor.clinic_id,
                Block.removed_at.is_(None),
                or_(Block.professional_id == profesional, Block.chair_id == sillon),
                Block.starts_at < hasta + timedelta(days=1),
                Block.ends_at > desde,
            )
        )
        return [
            Scoped(None if f.professional_id == profesional else f.chair_id, f.starts_at, f.ends_at)
            for f in filas
        ]

    # ------------------------------------------------------------------- listado

    def _list_stmt(self) -> Select[Any]:
        return select(WaitlistOffer).where(WaitlistOffer.clinic_id == self.actor.clinic_id)

    async def list(
        self,
        *,
        statuses: list[WaitlistOfferStatus] | None,
        desde: datetime | None,
        hasta: datetime | None,
        cursor: str | None,
        limit: int,
    ) -> OfferPage:
        """Ofertas por fecha de creación descendente; `from`/`to` filtran `created_at`."""
        stmt = self._list_stmt()
        if statuses:
            stmt = stmt.where(WaitlistOffer.status.in_(statuses))
        if desde is not None:
            stmt = stmt.where(WaitlistOffer.created_at >= desde)
        if hasta is not None:
            stmt = stmt.where(WaitlistOffer.created_at < hasta)
        if cursor:
            ts, ultimo = decode_cursor(cursor)
            stmt = stmt.where(
                or_(
                    WaitlistOffer.created_at < ts,
                    and_(WaitlistOffer.created_at == ts, WaitlistOffer.id < ultimo),
                )
            )
        filas = list(
            (
                await self.session.execute(
                    stmt.order_by(WaitlistOffer.created_at.desc(), WaitlistOffer.id.desc()).limit(
                        limit + 1
                    )
                )
            ).scalars()
        )
        siguiente = None
        if len(filas) > limit:
            filas = filas[:limit]
            siguiente = encode_cursor(filas[-1].created_at, filas[-1].id)
        return OfferPage(items=[OfferRead.model_validate(o) for o in filas], next_cursor=siguiente)


def _matches(entry: WaitingListEntry, starts_at: datetime, ends_at: datetime, tz: ZoneInfo) -> bool:
    """El hueco cae en el período, la franja y los días de la entrada."""
    inicio = starts_at.astimezone(tz)
    fin = ends_at.astimezone(tz)
    if not entry.date_from <= inicio.date() <= entry.date_to:
        return False
    if entry.weekdays is not None and inicio.weekday() not in entry.weekdays:
        return False
    if entry.time_from is not None and entry.time_to is not None:
        if inicio.time() < entry.time_from or fin.date() != inicio.date():
            return False
        if fin.time() > entry.time_to:
            return False
    return True
