"""Schemas del dominio agenda (stub C-01; bordes reales en C-04/C-05)."""

from pydantic import BaseModel, ConfigDict


class AgendaStub(BaseModel):
    """Placeholder con validación estricta de borde."""

    model_config = ConfigDict(extra="forbid")

    ping: str = "ok"
