"""Schemas del dominio clinic: bordes con validación estricta (regla dura 2)."""

from __future__ import annotations

import uuid
from decimal import Decimal
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
# Teléfono crudo (C-08): el servicio lo normaliza a E.164; acá solo se acota el largo.
ContactPhone = Annotated[str, Field(min_length=1, max_length=32)]
# Umbral mensual de costo de WhatsApp en USD (C-14, D8): `0` = sin alerta; hasta 6 decimales
# (el costo se guarda en micro-dólares, RN-WA-05).
MonthlyAlertUsd = Annotated[Decimal, Field(ge=0, le=100_000, max_digits=12, decimal_places=6)]


class ClinicPolicies(BaseModel):
    """Políticas operativas de la clínica (US-004)."""

    cancellation_window_hours: int
    reminder_steps: list[ReminderStep]
    max_overbookings_per_day: int
    waitlist_offer_ttl_hours: int
    # Teléfono de derivación pública en E.164 (C-08, RN-ON-04/RN-CX-01). `None` = sin cargar.
    contact_phone: str | None
    # Umbral mensual de costo de WhatsApp en USD con 6 decimales (C-14). `None` = sin alerta.
    whatsapp_monthly_alert_usd: str | None = None


class ClinicPoliciesUpdate(BaseModel):
    """Cambios parciales; ningún campo admite `null` y los pasos no repiten `offset_h`."""

    model_config = ConfigDict(extra="forbid")

    cancellation_window_hours: CancellationWindowHours | None = None
    reminder_steps: ReminderSteps | None = None
    max_overbookings_per_day: MaxOverbookings | None = None
    waitlist_offer_ttl_hours: OfferTtlHours | None = None
    contact_phone: ContactPhone | None = None
    whatsapp_monthly_alert_usd: MonthlyAlertUsd | None = None

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
