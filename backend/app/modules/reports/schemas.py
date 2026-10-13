"""Schemas del dominio reports (stub C-01; bordes reales en C-13)."""

from pydantic import BaseModel, ConfigDict


class ReportsStub(BaseModel):
    """Placeholder con validación estricta de borde."""

    model_config = ConfigDict(extra="forbid")

    ping: str = "ok"
