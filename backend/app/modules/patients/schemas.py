"""Bordes Pydantic de pacientes para el personal (C-05, US-011 CA-1).

`extra="forbid"` (regla 2). Teléfono y email llegan como texto libre y se
validan en el servicio: un error de validación de Pydantic devolvería el valor
recibido en el cuerpo del 422, y eso sería PII (regla 13).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

FullName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Dni = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]


class PatientCreate(BaseModel):
    """Alta rápida: nombre y al menos un contacto (el CHECK de la base lo refuerza)."""

    model_config = ConfigDict(extra="forbid")

    full_name: FullName
    phone: str | None = None
    email: str | None = None
    dni: Dni | None = None
    whatsapp_opt_in: bool = False


class PatientRead(BaseModel):
    """Vista del personal autorizado (admin y recepción)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    phone_e164: str | None
    email: str | None
    dni: str | None
    whatsapp_opt_in: bool


class PatientSearchResult(BaseModel):
    """Resultado por relevancia (máximo 20): no es un listado paginable."""

    items: list[PatientRead]
