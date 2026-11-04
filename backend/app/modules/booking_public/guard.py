"""Verificación anti-bot conectable de la reserva pública (C-07, D2).

En v1 no hay CAPTCHA (decisión del usuario, 2026-11-04): la protección es el rate-limit en
Redis y la anti-enumeración. `BotGuard` es el punto de extensión: un futuro Turnstile/reCAPTCHA
lee su token de una cabecera (`X-Bot-Token`), de modo que no cambia el schema del cuerpo
(`extra='forbid'`) ni el router; solo la implementación que devuelve `get_bot_guard`,
seleccionada por el setting `BOT_GUARD`.
"""

from __future__ import annotations

from typing import Annotated, Literal, Protocol

from fastapi import Depends, Request

from app.core.settings import Settings, get_settings


class BotGuard(Protocol):
    """Verificador anti-bot; rechaza con `DomainError(403, "bot_check_failed")`."""

    async def verify(self, request: Request, *, action: Literal["read", "book"]) -> None: ...


class NoopBotGuard:
    """v1: no exige desafío."""

    async def verify(self, request: Request, *, action: Literal["read", "book"]) -> None:
        return None


def get_bot_guard(settings: Annotated[Settings, Depends(get_settings)]) -> BotGuard:
    """Dependency: el verificador configurado (`BOT_GUARD=noop` en v1)."""
    _ = settings.BOT_GUARD  # único valor soportado hoy: "noop"
    return NoopBotGuard()
