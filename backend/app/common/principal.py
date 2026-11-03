"""Principal autenticado del personal (C-03).

El principal se construye **desde la fila de `user`** (rol, `clinic_id`,
`professional_id`, `active`), nunca desde los claims del access token: un token
válido por firma con un rol manipulado no otorga permisos (spec `identity/rbac`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.models import UserRole


@dataclass(frozen=True, slots=True)
class Principal:
    """Identidad efectiva de un request autenticado (inmutable)."""

    user_id: uuid.UUID
    clinic_id: uuid.UUID
    email: str
    roles: frozenset[UserRole]
    professional_id: uuid.UUID | None
    sid: str
    must_change_password: bool
