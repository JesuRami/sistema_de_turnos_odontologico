"""Bordes Pydantic de gestión de usuarios del personal (C-03).

`extra="forbid"` en todos los schemas: un `clinic_id` en el body responde `422`
(regla 2 + tenant solo desde el principal). La contraseña es `SecretStr` y nunca
se devuelve.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, model_validator

from app.models import UserRole
from app.modules.auth.schemas import Email, Password


class UserCreate(BaseModel):
    """Alta de personal; el `clinic_id` sale del principal, no del body."""

    model_config = ConfigDict(extra="forbid")

    email: Email
    password: Password
    role: UserRole
    professional_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _odontologo_requiere_profesional(self) -> UserCreate:
        if self.role is UserRole.ODONTOLOGO and self.professional_id is None:
            raise ValueError("el rol odontologo exige professional_id")
        return self


class UserUpdate(BaseModel):
    """Cambios parciales; `model_fields_set` distingue ausencia de `null`."""

    model_config = ConfigDict(extra="forbid")

    email: Email | None = None
    role: UserRole | None = None
    active: bool | None = None
    professional_id: uuid.UUID | None = None


class UserRead(BaseModel):
    """Usuario público: sin `password_hash` ni contraseña."""

    id: uuid.UUID
    email: str
    role: UserRole
    active: bool
    must_change_password: bool
    professional_id: uuid.UUID | None
    last_login_at: datetime | None
    created_at: datetime


class UserPage(BaseModel):
    """Página por cursor (sin `OFFSET`)."""

    items: list[UserRead]
    next_cursor: str | None


class PasswordReset(BaseModel):
    """Contraseña provisoria fijada por un admin."""

    model_config = ConfigDict(extra="forbid")

    new_password: Password
