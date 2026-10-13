"""Schemas del dominio auth (stub C-01; bordes reales en C-03)."""

from pydantic import BaseModel, ConfigDict


class AuthStub(BaseModel):
    """Placeholder con validación estricta de borde."""

    model_config = ConfigDict(extra="forbid")

    ping: str = "ok"
