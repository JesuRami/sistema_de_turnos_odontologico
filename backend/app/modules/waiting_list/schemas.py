"""Bordes de la lista de espera (C-12, D11). Todo esquema de entrada con `extra='forbid'` (regla 2).

Las preferencias se validan en el servicio para responder códigos estables (`invalid_range`,
`invalid_time_window`, `invalid_weekdays`…), no la lista genérica de Pydantic.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import ActorType, WaitingListStatus, WaitlistEventType, WaitlistOfferStatus
from app.modules.appointments.schemas import PatientContact, PatientMinimal

_TEXT_MAX = 1000  # tope del borde; el servicio aplica el largo real (200) con su código


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EntryPreferences(_Strict):
    """Profesional y preferencias comunes al alta de recepción y a la anotación pública."""

    professional_id: uuid.UUID | None = None
    date_from: date
    date_to: date
    time_from: time | None = None
    time_to: time | None = None
    weekdays: list[int] | None = Field(default=None, max_length=14)


class EntryCreate(EntryPreferences):
    patient_id: uuid.UUID
    notes: str | None = Field(default=None, max_length=_TEXT_MAX)


class EntryUpdate(_Strict):
    """Campos editables de una entrada `waiting`; solo cambian los enviados."""

    professional_id: uuid.UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
    time_from: time | None = None
    time_to: time | None = None
    weekdays: list[int] | None = Field(default=None, max_length=14)
    notes: str | None = Field(default=None, max_length=_TEXT_MAX)

    preference_fields: ClassVar[tuple[str, ...]] = (
        "professional_id",
        "date_from",
        "date_to",
        "time_from",
        "time_to",
        "weekdays",
    )


class PriorityRequest(_Strict):
    reason: str | None = Field(default=None, max_length=_TEXT_MAX)


class PendingOfferRead(BaseModel):
    id: uuid.UUID
    professional_id: uuid.UUID
    chair_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
    expires_at: datetime
    mode: Literal["auto", "manual"]


class EntryRead(BaseModel):
    id: uuid.UUID
    status: WaitingListStatus
    source: Literal["reception", "online"]
    patient: PatientContact | PatientMinimal
    professional_id: uuid.UUID | None
    date_from: date
    date_to: date
    time_from: time | None
    time_to: time | None
    weekdays: list[int] | None
    notes: str | None
    prioritized_at: datetime | None
    priority_reason: str | None
    consecutive_expired: int
    closed_reason: str | None
    created_at: datetime
    pending_offer: PendingOfferRead | None


class EntryPage(BaseModel):
    items: list[EntryRead]
    next_cursor: str | None


class WaitlistEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event: WaitlistEventType
    offer_id: uuid.UUID | None
    actor_type: ActorType
    actor_user_id: uuid.UUID | None
    payload: dict[str, Any]
    created_at: datetime


class WaitlistEventList(BaseModel):
    items: list[WaitlistEventRead]


# ----------------------------------------------------------------------------- ofertas


class OfferRead(BaseModel):
    """Oferta para el personal: hueco, estado y resultado, sin datos del paciente."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entry_id: uuid.UUID
    professional_id: uuid.UUID
    chair_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
    expires_at: datetime
    status: WaitlistOfferStatus
    mode: Literal["auto", "manual"]
    appointment_id: uuid.UUID | None
    closed_reason: str | None
    responded_at: datetime | None
    created_at: datetime


class OfferPage(BaseModel):
    items: list[OfferRead]
    next_cursor: str | None


class ManualOfferCreate(_Strict):
    professional_id: uuid.UUID
    chair_id: uuid.UUID
    starts_at: datetime
    fifo_skip_reason: str | None = Field(default=None, max_length=_TEXT_MAX)


class SlotCandidate(BaseModel):
    professional_id: uuid.UUID
    chair_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime


class SlotList(BaseModel):
    timezone: str
    items: list[SlotCandidate]


class DeclineRequest(_Strict):
    leave_list: bool = False


class AcceptedOffer(BaseModel):
    """Resultado de aceptar: la oferta y el turno creado."""

    offer: OfferRead
    appointment_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
