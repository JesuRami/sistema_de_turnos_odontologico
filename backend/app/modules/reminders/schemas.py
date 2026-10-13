"""Schemas del dominio reminders (stub C-01; bordes reales en C-09)."""

from pydantic import BaseModel, ConfigDict


class RemindersStub(BaseModel):
    """Placeholder con validación estricta de borde."""

    model_config = ConfigDict(extra="forbid")

    ping: str = "ok"
