"""Schemas del dominio clinic (stub C-01; bordes reales en C-02)."""

from pydantic import BaseModel, ConfigDict


class ClinicStub(BaseModel):
    """Placeholder con validación estricta de borde."""

    model_config = ConfigDict(extra="forbid")

    ping: str = "ok"
