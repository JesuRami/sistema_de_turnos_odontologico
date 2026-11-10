"""Entradas de la lista de espera (C-12; spec waitlist/entries, D1/D10/D11).

Único escritor de `waiting_list_entry` fuera del motor de ofertas: alta (recepción o pública),
edición, retiro, prioridad y lecturas. Cada mutación escribe su `waitlist_event` en la misma
transacción. Todo se filtra por la clínica del actor (regla 4); el odontólogo ve solo las entradas
de su profesional y de "cualquiera", sin contacto ni notas.

RN-LE-01 la impone el índice único parcial `uq_waiting_list_entry_active`: el chequeo previo da el
`409` con el id de la existente y el índice resuelve la carrera.
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from sqlalchemy import Select, and_, or_, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import DomainError
from app.common.free_text import clean_free_text
from app.core.settings import Settings
from app.models import (
    ACTIVE_ENTRY_STATUSES,
    Clinic,
    Patient,
    Professional,
    WaitingListEntry,
    WaitingListStatus,
    WaitlistEvent,
    WaitlistEventType,
    WaitlistOffer,
    WaitlistOfferStatus,
)
from app.models.waiting_list import NOTES_MAX_LENGTH, REASON_MAX_LENGTH
from app.modules.appointments.audit import Actor
from app.modules.appointments.schemas import PatientContact, PatientMinimal
from app.modules.waiting_list.audit import close_pending_offer, record_event
from app.modules.waiting_list.schemas import (
    EntryCreate,
    EntryPage,
    EntryRead,
    EntryUpdate,
    PendingOfferRead,
    WaitlistEventList,
    WaitlistEventRead,
)

PRIORITY_REASON_MIN = 10
_UNIQUE_ACTIVE = "uq_waiting_list_entry_active"
_PREFERENCES = ("professional_id", "date_from", "date_to", "time_from", "time_to", "weekdays")


@dataclass(frozen=True, slots=True)
class Preferences:
    professional_id: uuid.UUID | None
    date_from: date
    date_to: date
    time_from: time | None
    time_to: time | None
    weekdays: list[int] | None


async def clinic_tz(session: AsyncSession, clinic_id: uuid.UUID) -> ZoneInfo:
    tz = await session.scalar(select(Clinic.timezone).where(Clinic.id == clinic_id))
    return ZoneInfo(tz or "America/Argentina/Buenos_Aires")


def validate_preferences(
    prefs: Preferences, *, today: date, horizon_days: int, check_start: bool = True
) -> Preferences:
    """Período desde hoy y dentro del horizonte, franja ambos-o-ninguno, días 0–6 sin repetir.

    `check_start=False` (edición sin tocar `date_from`): una entrada cuyo período ya empezó puede
    seguir editando su franja; el fin sí tiene que ser hoy o posterior.
    """
    if check_start and prefs.date_from < today:
        raise DomainError(422, "invalid_range")
    if prefs.date_to < prefs.date_from or prefs.date_to < today:
        raise DomainError(422, "invalid_range")
    if prefs.date_to > today + timedelta(days=horizon_days):
        raise DomainError(422, "range_too_large")
    if (prefs.time_from is None) != (prefs.time_to is None):
        raise DomainError(422, "invalid_time_window")
    if prefs.time_from is not None and prefs.time_to is not None:
        if prefs.time_to <= prefs.time_from:
            raise DomainError(422, "invalid_time_window")
    dias = prefs.weekdays
    if dias is not None:
        if not dias or len(set(dias)) != len(dias) or any(d < 0 or d > 6 for d in dias):
            raise DomainError(422, "invalid_weekdays")
        dias = sorted(dias)
    return Preferences(
        prefs.professional_id, prefs.date_from, prefs.date_to, prefs.time_from, prefs.time_to, dias
    )


class _HasPreferences(Protocol):
    professional_id: uuid.UUID | None
    date_from: date
    date_to: date
    time_from: time | None
    time_to: time | None
    weekdays: list[int] | None


def preferences_of(payload: _HasPreferences) -> Preferences:
    return Preferences(
        payload.professional_id,
        payload.date_from,
        payload.date_to,
        payload.time_from,
        payload.time_to,
        payload.weekdays,
    )


def _prefs_payload(prefs: Preferences) -> dict[str, Any]:
    return {campo: getattr(prefs, campo) for campo in _PREFERENCES}


# ----------------------------------------------------------------------------- cursor


def _encode_cursor(entry: WaitingListEntry) -> str:
    crudo = {
        "p": entry.prioritized_at.isoformat() if entry.prioritized_at else None,
        "c": entry.created_at.isoformat(),
        "i": str(entry.id),
    }
    return base64.urlsafe_b64encode(json.dumps(crudo).encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime | None, datetime, uuid.UUID]:
    try:
        crudo = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        prioridad = datetime.fromisoformat(crudo["p"]) if crudo["p"] else None
        return prioridad, datetime.fromisoformat(crudo["c"]), uuid.UUID(crudo["i"])
    except (ValueError, KeyError, TypeError, binascii.Error, UnicodeDecodeError):
        raise DomainError(422, "invalid_cursor") from None


def _after(cursor: str) -> Any:
    """Predicado keyset para el orden `prioritized_at NULLS LAST, created_at, id`."""
    prioridad, creado, ultimo = _decode_cursor(cursor)
    E = WaitingListEntry
    if prioridad is None:
        return and_(E.prioritized_at.is_(None), tuple_(E.created_at, E.id) > (creado, ultimo))
    return or_(
        and_(
            E.prioritized_at.is_not(None),
            tuple_(E.prioritized_at, E.created_at, E.id) > (prioridad, creado, ultimo),
        ),
        E.prioritized_at.is_(None),
    )


# ----------------------------------------------------------------------------- servicio


class EntriesService:
    """Casos de uso de entradas para un actor de la clínica y un instante dados."""

    def __init__(self, session: AsyncSession, actor: Actor, now: datetime, settings: Settings):
        self.session = session
        self.actor = actor
        self.now = now
        self.settings = settings

    # ------------------------------------------------------------------- alcance

    def _scoped(self, stmt: Select[Any]) -> Select[Any]:
        stmt = stmt.where(WaitingListEntry.clinic_id == self.actor.clinic_id)
        if self.actor.only_dentist:
            if self.actor.professional_id is None:
                raise DomainError(403, "forbidden_scope")
            stmt = stmt.where(
                or_(
                    WaitingListEntry.professional_id == self.actor.professional_id,
                    WaitingListEntry.professional_id.is_(None),
                )
            )
        return stmt

    async def locked(self, entry_id: uuid.UUID) -> WaitingListEntry:
        entry: WaitingListEntry | None = (
            await self.session.execute(
                self._scoped(select(WaitingListEntry))
                .where(WaitingListEntry.id == entry_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if entry is None:
            raise DomainError(404, "not_found")
        return entry

    async def _today(self) -> date:
        return self.now.astimezone(await clinic_tz(self.session, self.actor.clinic_id)).date()

    async def _validate(self, prefs: Preferences, *, check_start: bool = True) -> Preferences:
        validas = validate_preferences(
            prefs,
            today=await self._today(),
            horizon_days=self.settings.PUBLIC_BOOKING_HORIZON_DAYS,
            check_start=check_start,
        )
        if validas.professional_id is not None:
            activo = await self.session.scalar(
                select(Professional.active).where(
                    Professional.clinic_id == self.actor.clinic_id,
                    Professional.id == validas.professional_id,
                )
            )
            if activo is None:
                raise DomainError(422, "invalid_resource")
            if not activo:
                raise DomainError(409, "resource_inactive")
        return validas

    async def _existing(
        self, patient_id: uuid.UUID, professional_id: uuid.UUID | None
    ) -> uuid.UUID | None:
        existente: uuid.UUID | None = await self.session.scalar(
            select(WaitingListEntry.id).where(
                WaitingListEntry.clinic_id == self.actor.clinic_id,
                WaitingListEntry.patient_id == patient_id,
                WaitingListEntry.professional_id.is_not_distinct_from(professional_id),
                WaitingListEntry.status.in_(ACTIVE_ENTRY_STATUSES),
            )
        )
        return existente

    async def _raise_duplicate(
        self, patient_id: uuid.UUID, professional_id: uuid.UUID | None
    ) -> None:
        existente = await self._existing(patient_id, professional_id)
        raise DomainError(
            409,
            "already_waiting",
            extra={"entry_id": str(existente)} if existente and self.actor.user_id else None,
        )

    # ---------------------------------------------------------------------- alta

    async def create(self, payload: EntryCreate) -> EntryRead:
        """Alta de recepción: paciente existente de la clínica y nota operativa opcional."""
        notas = clean_free_text(payload.notes, max_length=NOTES_MAX_LENGTH, code="invalid_note")
        paciente = await self.session.scalar(
            select(Patient.id).where(
                Patient.clinic_id == self.actor.clinic_id,
                Patient.id == payload.patient_id,
                Patient.archived_at.is_(None),
                Patient.merged_into_patient_id.is_(None),
            )
        )
        if paciente is None:
            raise DomainError(422, "invalid_patient")
        entry = await self.add(
            payload.patient_id,
            await self._validate(preferences_of(payload)),
            source="reception",
            notes=notas,
        )
        await self.session.commit()
        return await self.get(entry.id)

    async def add(
        self,
        patient_id: uuid.UUID,
        prefs: Preferences,
        *,
        source: str,
        notes: str | None = None,
    ) -> WaitingListEntry:
        """Inserta la entrada y su evento sin commit (la anotación pública lo reutiliza).

        `prefs` ya viene validado.
        """
        if await self._existing(patient_id, prefs.professional_id) is not None:
            await self._raise_duplicate(patient_id, prefs.professional_id)
        entry = WaitingListEntry(
            clinic_id=self.actor.clinic_id,
            patient_id=patient_id,
            notes=notes,
            source=source,
            status=WaitingListStatus.WAITING,
            created_by_user_id=self.actor.user_id,
            **_prefs_payload(prefs),
        )
        try:
            async with self.session.begin_nested():
                self.session.add(entry)
                await self.session.flush()
        except IntegrityError as exc:
            if _UNIQUE_ACTIVE not in str(exc.orig):
                raise
            await self._raise_duplicate(patient_id, prefs.professional_id)
        await record_event(
            self.session,
            self.actor,
            clinic_id=entry.clinic_id,
            entry_id=entry.id,
            event=WaitlistEventType.ENTRY_CREATED,
            payload={"source": source, **_prefs_payload(prefs), "has_notes": notes is not None},
        )
        return entry

    # ------------------------------------------------------------------- edición

    def _assert_active(self, entry: WaitingListEntry) -> None:
        if entry.status not in ACTIVE_ENTRY_STATUSES:
            raise DomainError(409, "entry_closed")

    async def update(self, entry_id: uuid.UUID, payload: EntryUpdate) -> EntryRead:
        entry = await self.locked(entry_id)
        self._assert_active(entry)
        if entry.status is WaitingListStatus.OFFERED:
            raise DomainError(409, "entry_offered")
        enviados = payload.model_fields_set
        antes = Preferences(**{c: getattr(entry, c) for c in _PREFERENCES})
        nuevas = Preferences(
            **{c: getattr(payload, c) if c in enviados else getattr(entry, c) for c in _PREFERENCES}
        )
        if nuevas != antes:
            nuevas = await self._validate(nuevas, check_start=nuevas.date_from != antes.date_from)
        notas = entry.notes
        if "notes" in enviados:
            notas = clean_free_text(payload.notes, max_length=NOTES_MAX_LENGTH, code="invalid_note")
        cambiadas = [c for c in _PREFERENCES if getattr(antes, c) != getattr(nuevas, c)]
        notas_cambiadas = notas != entry.notes
        if not cambiadas and not notas_cambiadas:
            return await self.get(entry_id)
        if nuevas.professional_id != antes.professional_id:
            otra = await self._existing(entry.patient_id, nuevas.professional_id)
            if otra is not None and otra != entry.id:
                await self._raise_duplicate(entry.patient_id, nuevas.professional_id)
        for campo in cambiadas:
            setattr(entry, campo, getattr(nuevas, campo))
        entry.notes = notas
        await self.session.flush()
        await record_event(
            self.session,
            self.actor,
            clinic_id=entry.clinic_id,
            entry_id=entry.id,
            event=WaitlistEventType.ENTRY_UPDATED,
            payload={
                "before": {c: getattr(antes, c) for c in cambiadas},
                "after": {c: getattr(nuevas, c) for c in cambiadas},
                "notes_changed": notas_cambiadas,
            },
        )
        await self.session.commit()
        return await self.get(entry_id)

    async def pending_offer(self, entry: WaitingListEntry) -> WaitlistOffer | None:
        oferta: WaitlistOffer | None = await self.session.scalar(
            select(WaitlistOffer)
            .where(
                WaitlistOffer.clinic_id == entry.clinic_id,
                WaitlistOffer.entry_id == entry.id,
                WaitlistOffer.status == WaitlistOfferStatus.PENDING,
            )
            .with_for_update()
        )
        return oferta

    async def withdraw(
        self, entry_id: uuid.UUID, *, reason: str = "withdrawn_by_staff"
    ) -> EntryRead:
        entry = await self.locked(entry_id)
        await self.withdraw_locked(entry, reason=reason)
        await self.session.commit()
        return await self.get(entry_id)

    async def withdraw_locked(self, entry: WaitingListEntry, *, reason: str) -> None:
        """Retiro sin commit; la oferta pendiente, si la hay, queda `cancelled`."""
        self._assert_active(entry)
        oferta = await self.pending_offer(entry)
        if oferta is not None:
            await close_pending_offer(
                self.session, self.actor, oferta, reason="entry_withdrawn", now=self.now
            )
            # El hueco que quedó libre rota a la siguiente entrada compatible (D3).
            from app.modules.waiting_list.engine import Slot, evaluate_slot

            await evaluate_slot(
                self.session, Slot.of_offer(oferta), now=self.now, settings=self.settings
            )
        entry.status = WaitingListStatus.WITHDRAWN
        entry.closed_reason = reason
        await self.session.flush()
        await record_event(
            self.session,
            self.actor,
            clinic_id=entry.clinic_id,
            entry_id=entry.id,
            event=WaitlistEventType.ENTRY_WITHDRAWN,
            payload={"reason": reason},
        )

    # ------------------------------------------------------------------ prioridad

    async def prioritize(self, entry_id: uuid.UUID, reason: str | None) -> EntryRead:
        motivo = clean_free_text(
            reason,
            max_length=REASON_MAX_LENGTH,
            min_length=PRIORITY_REASON_MIN,
            code="priority_reason_required",
        )
        assert motivo is not None
        entry = await self.locked(entry_id)
        self._assert_active(entry)
        entry.prioritized_at = self.now
        entry.priority_reason = motivo
        await self.session.flush()
        await record_event(
            self.session,
            self.actor,
            clinic_id=entry.clinic_id,
            entry_id=entry.id,
            event=WaitlistEventType.ENTRY_PRIORITIZED,
            payload={"reason": motivo},
        )
        await self.session.commit()
        return await self.get(entry_id)

    async def unprioritize(self, entry_id: uuid.UUID) -> EntryRead:
        entry = await self.locked(entry_id)
        self._assert_active(entry)
        if entry.prioritized_at is None:
            return await self.get(entry_id)
        entry.prioritized_at = None
        entry.priority_reason = None
        await self.session.flush()
        await record_event(
            self.session,
            self.actor,
            clinic_id=entry.clinic_id,
            entry_id=entry.id,
            event=WaitlistEventType.ENTRY_UNPRIORITIZED,
        )
        await self.session.commit()
        return await self.get(entry_id)

    # ------------------------------------------------------------------- lectura

    def _read_stmt(self) -> Select[Any]:
        return self._scoped(
            select(
                WaitingListEntry,
                Patient.full_name,
                Patient.phone_e164,
                Patient.email,
                WaitlistOffer,
            )
            .join(
                Patient,
                and_(
                    Patient.clinic_id == WaitingListEntry.clinic_id,
                    Patient.id == WaitingListEntry.patient_id,
                ),
            )
            .outerjoin(
                WaitlistOffer,
                and_(
                    WaitlistOffer.clinic_id == WaitingListEntry.clinic_id,
                    WaitlistOffer.entry_id == WaitingListEntry.id,
                    WaitlistOffer.status == WaitlistOfferStatus.PENDING,
                ),
            )
        )

    def _to_read(self, fila: Any) -> EntryRead:
        entry: WaitingListEntry = fila[0]
        oferta: WaitlistOffer | None = fila[4]
        patient: PatientContact | PatientMinimal
        if self.actor.only_dentist:
            patient = PatientMinimal(id=entry.patient_id, full_name=fila[1])
        else:
            patient = PatientContact(
                id=entry.patient_id, full_name=fila[1], phone_e164=fila[2], email=fila[3]
            )
        return EntryRead(
            id=entry.id,
            status=entry.status,
            source=entry.source,  # type: ignore[arg-type]
            patient=patient,
            professional_id=entry.professional_id,
            date_from=entry.date_from,
            date_to=entry.date_to,
            time_from=entry.time_from,
            time_to=entry.time_to,
            weekdays=entry.weekdays,
            notes=None if self.actor.only_dentist else entry.notes,
            prioritized_at=entry.prioritized_at,
            priority_reason=entry.priority_reason,
            consecutive_expired=entry.consecutive_expired,
            closed_reason=entry.closed_reason,
            created_at=entry.created_at,
            pending_offer=(
                PendingOfferRead(
                    id=oferta.id,
                    professional_id=oferta.professional_id,
                    chair_id=oferta.chair_id,
                    starts_at=oferta.starts_at,
                    ends_at=oferta.ends_at,
                    expires_at=oferta.expires_at,
                    mode=oferta.mode,  # type: ignore[arg-type]
                )
                if oferta is not None
                else None
            ),
        )

    async def get(self, entry_id: uuid.UUID) -> EntryRead:
        fila = (
            await self.session.execute(self._read_stmt().where(WaitingListEntry.id == entry_id))
        ).one_or_none()
        if fila is None:
            raise DomainError(404, "not_found")
        return self._to_read(fila)

    async def list(
        self,
        *,
        statuses: Sequence[WaitingListStatus] | None,
        professional_id: uuid.UUID | None,
        desde: date | None,
        hasta: date | None,
        cursor: str | None,
        limit: int,
    ) -> EntryPage:
        if desde is not None and hasta is not None and desde > hasta:
            raise DomainError(422, "invalid_range")
        stmt = self._read_stmt().where(
            WaitingListEntry.status.in_(list(statuses or ACTIVE_ENTRY_STATUSES))
        )
        if professional_id is not None:
            stmt = stmt.where(
                or_(
                    WaitingListEntry.professional_id == professional_id,
                    WaitingListEntry.professional_id.is_(None),
                )
            )
        if desde is not None:
            stmt = stmt.where(WaitingListEntry.date_to >= desde)
        if hasta is not None:
            stmt = stmt.where(WaitingListEntry.date_from <= hasta)
        if cursor:
            stmt = stmt.where(_after(cursor))
        filas = (
            await self.session.execute(
                stmt.order_by(
                    WaitingListEntry.prioritized_at.asc().nulls_last(),
                    WaitingListEntry.created_at,
                    WaitingListEntry.id,
                ).limit(limit + 1)
            )
        ).all()
        siguiente = None
        if len(filas) > limit:
            filas = filas[:limit]
            siguiente = _encode_cursor(filas[-1][0])
        return EntryPage(items=[self._to_read(f) for f in filas], next_cursor=siguiente)

    async def events(self, entry_id: uuid.UUID) -> WaitlistEventList:
        existe = await self.session.scalar(
            self._scoped(select(WaitingListEntry.id)).where(WaitingListEntry.id == entry_id)
        )
        if existe is None:
            raise DomainError(404, "not_found")
        filas = (
            await self.session.execute(
                select(WaitlistEvent)
                .where(
                    WaitlistEvent.clinic_id == self.actor.clinic_id,
                    WaitlistEvent.entry_id == entry_id,
                )
                .order_by(WaitlistEvent.created_at, WaitlistEvent.id)
            )
        ).scalars()
        return WaitlistEventList(items=[WaitlistEventRead.model_validate(e) for e in filas])
