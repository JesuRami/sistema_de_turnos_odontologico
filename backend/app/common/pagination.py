"""Paginación por cursor (regla dura 8: nunca OFFSET grande en agenda/reportes)."""

from pydantic import BaseModel, ConfigDict, Field


class CursorPage(BaseModel):
    """Parámetros de paginación por cursor."""

    model_config = ConfigDict(extra="forbid")

    cursor: str | None = Field(default=None)
    limit: int = Field(default=50, ge=1, le=200)
