"""Schemas del dominio waiting_list (stub C-01; bordes reales en C-12)."""

from pydantic import BaseModel, ConfigDict


class WaitingListStub(BaseModel):
    """Placeholder con validación estricta de borde."""

    model_config = ConfigDict(extra="forbid")

    ping: str = "ok"
