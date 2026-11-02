"""Schemas del dominio clinic: bordes con validación estricta (regla dura 2)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ClinicStub(BaseModel):
    """Placeholder con validación estricta de borde (usado por `/clinic/ping`)."""

    model_config = ConfigDict(extra="forbid")

    ping: str = "ok"


class ReminderStep(BaseModel):
    """Paso de recordatorio de `clinic.reminder_steps`: `{offset_h, channel}`."""

    model_config = ConfigDict(extra="forbid")

    offset_h: int = Field(gt=0)
    channel: Literal["whatsapp", "email"]
