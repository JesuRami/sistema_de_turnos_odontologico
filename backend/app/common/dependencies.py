"""Dependencias comunes de autorización (C-03): gate de clave y roles.

`require_roles` es la **única puerta** de autorización por rol: incluye el gate
de contraseña provisoria para que ningún endpoint protegido pueda olvidarlo
(design §9). El tenant y el rol salen del `Principal` cargado de la DB, nunca
del cuerpo ni del token.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends

from app.common.exceptions import DomainError
from app.common.principal import Principal
from app.core.deps import get_current_principal
from app.models import UserRole

logger = logging.getLogger("app.auth.rbac")

PrincipalDep = Annotated[Principal, Depends(get_current_principal)]


async def require_active_password(principal: PrincipalDep) -> Principal:
    """Bloquea la API protegida mientras la contraseña siga siendo provisoria.

    `/auth/me`, `/auth/change-password` y `/auth/logout` usan
    `get_current_principal` directo, sin este gate (spec `identity/staff-auth`).
    """
    if principal.must_change_password:
        raise DomainError(403, "password_change_required")
    return principal


def require_roles(*roles: UserRole | str) -> Callable[..., Awaitable[Principal]]:
    """Fábrica de dependencies: exige al menos uno de `roles`.

    Un rol desconocido falla al construir la dependency (arranque), no en el
    request. Si el principal no tiene ninguno → `403 forbidden_role`; los roles
    exigidos quedan solo en el log, nunca en el cuerpo.
    """
    permitidos = frozenset(UserRole(rol) for rol in roles)

    async def _checker(
        principal: Annotated[Principal, Depends(require_active_password)],
    ) -> Principal:
        if not (principal.roles & permitidos):
            logger.warning(
                "forbidden_role requeridos=%s",
                sorted(rol.value for rol in permitidos),
            )
            raise DomainError(403, "forbidden_role")
        return principal

    return _checker
