"""Bordes Pydantic de la reserva pública (C-07).

Entradas con `extra='forbid'` (regla 2): el paciente solo elige profesional y horario; nunca
sillón, duración, estado, origen ni `clinic_id`. Las salidas exponen solo lo ofrecible
(RN-ON-01): sin sillones, estados, ids de turnos ni datos de pacientes.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    StringConstraints,
)

PHONE_MAX = 32
EMAIL_MAX = 254

FullName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Warning_ = Literal["phone_invalid_email_channel", "whatsapp_declined_email_channel"]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfessionalPublic(BaseModel):
    id: uuid.UUID
    display_name: str


class CatalogRead(BaseModel):
    name: str
    timezone: str
    professionals: list[ProfessionalPublic]


class SlotRead(BaseModel):
    starts_at: datetime
    ends_at: datetime
    professional_id: uuid.UUID


class AvailabilityRead(BaseModel):
    timezone: str
    slots: list[SlotRead]


class PatientInput(_Input):
    """Datos del paciente; el valor crudo del teléfono/email se valida en el servicio."""

    full_name: FullName
    phone: Annotated[str, StringConstraints(max_length=PHONE_MAX)] | None = None
    email: Annotated[str, StringConstraints(max_length=EMAIL_MAX)] | None = None
    whatsapp_opt_in: bool | None = None
    privacy_accepted: bool


class BookingCreate(_Input):
    professional_id: uuid.UUID
    starts_at: AwareDatetime
    patient: PatientInput


class BookingCreated(BaseModel):
    starts_at: datetime
    ends_at: datetime
    professional_id: uuid.UUID
    channel: Literal["whatsapp", "email"]
    warnings: list[Warning_]
    manage_url: str


class AlternativeSlot(BaseModel):
    starts_at: datetime
    ends_at: datetime
    professional_id: uuid.UUID
