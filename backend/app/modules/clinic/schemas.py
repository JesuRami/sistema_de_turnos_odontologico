"""Schemas del dominio clinic: bordes con validación estricta (regla dura 2)."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReminderStep(BaseModel):
    """Paso de recordatorio de `clinic.reminder_steps`: `{offset_h, channel}`."""

    model_config = ConfigDict(extra="forbid")

    offset_h: int = Field(gt=0)
    channel: Literal["whatsapp", "email"]


ReminderSteps = Annotated[list[ReminderStep], Field(min_length=1, max_length=5)]
CancellationWindowHours = Annotated[int, Field(ge=0, le=720)]
MaxOverbookings = Annotated[int, Field(ge=0, le=20)]
OfferTtlHours = Annotated[int, Field(gt=0, le=72)]


class ClinicPolicies(BaseModel):
    """Políticas operativas de la clínica (US-004)."""

    cancellation_window_hours: int
    reminder_steps: list[ReminderStep]
    max_overbookings_per_day: int
    waitlist_offer_ttl_hours: int


class ClinicPoliciesUpdate(BaseModel):
    """Cambios parciales; ningún campo admite `null` y los pasos no repiten `offset_h`."""

    model_config = ConfigDict(extra="forbid")

    cancellation_window_hours: CancellationWindowHours | None = None
    reminder_steps: ReminderSteps | None = None
    max_overbookings_per_day: MaxOverbookings | None = None
    waitlist_offer_ttl_hours: OfferTtlHours | None = None

    @model_validator(mode="after")
    def _valida(self) -> ClinicPoliciesUpdate:
        for campo in self.model_fields_set:
            if getattr(self, campo) is None:
                raise ValueError(f"{campo} no admite null")
        if self.reminder_steps is not None:
            offsets = [paso.offset_h for paso in self.reminder_steps]
            if len(set(offsets)) != len(offsets):
                raise ValueError("reminder_steps no puede repetir offset_h")
        return self


class ClinicProfile(BaseModel):
    """Perfil de la clínica para todo el personal (C-06): nombre y zona horaria."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    timezone: str
