"""Bordes Pydantic del dominio auth (C-03).

Todos los schemas de borde usan `extra="forbid"` (regla dura 2). Las
contraseñas viajan como `SecretStr` y nunca se serializan en respuestas ni logs.
No se acepta `clinic_id` en ningún body: el tenant sale del principal.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints, model_validator

from app.models import UserRole

PASSWORD_MIN = 12
PASSWORD_MAX = 128

# Sin dependencia nueva (`email-validator`): validación equivalente y acotada.
Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    ),
]
Password = Annotated[SecretStr, Field(min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)]


class LoginRequest(BaseModel):
    """Credenciales de login (email normalizado a minúsculas)."""

    model_config = ConfigDict(extra="forbid")

    email: Email
    password: SecretStr = Field(min_length=1, max_length=PASSWORD_MAX)


class UserProfile(BaseModel):
    """Identidad pública del usuario (nunca incluye hash ni tokens)."""

    id: uuid.UUID
    email: str
    role: UserRole
    clinic_id: uuid.UUID
    professional_id: uuid.UUID | None
    must_change_password: bool
    last_login_at: datetime | None


class LoginResponse(BaseModel):
    """Access token de vida corta + datos del usuario; el refresh va en cookie."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserProfile


class AccessTokenResponse(BaseModel):
    """Respuesta de refresh: solo access nuevo (el refresh viaja en cookie)."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class ChangePasswordRequest(BaseModel):
    """Cambio de contraseña propio: actual + nueva (12–128, distinta)."""

    model_config = ConfigDict(extra="forbid")

    current_password: SecretStr = Field(min_length=1, max_length=PASSWORD_MAX)
    new_password: Password

    @model_validator(mode="after")
    def _nueva_distinta(self) -> ChangePasswordRequest:
        if self.current_password.get_secret_value() == self.new_password.get_secret_value():
            raise ValueError("la contraseña nueva debe ser distinta de la actual")
        return self
