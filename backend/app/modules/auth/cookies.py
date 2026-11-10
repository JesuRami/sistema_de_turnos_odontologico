"""Cookie de refresh por entorno (C-03 design §13).

- `ENV=dev`: `refresh_token`, `HttpOnly`, `SameSite=Lax`, sin `Secure`.
- `ENV=prod`: `__Host-refresh_token` (obliga `Secure`, `Path=/` y sin `Domain`).
- Vigencia absoluta: `Max-Age = JWT_REFRESH_DAYS × 86400`.
"""

from __future__ import annotations

from fastapi import Response

from app.core.settings import Settings


def refresh_cookie_name(settings: Settings) -> str:
    """Nombre de la cookie según entorno (`__Host-` solo en prod)."""
    return "__Host-refresh_token" if settings.ENV == "prod" else "refresh_token"


def refresh_cookie_max_age(settings: Settings) -> int:
    """Vigencia absoluta de la cookie/familia en segundos."""
    return settings.JWT_REFRESH_DAYS * 86400


def set_refresh_cookie(response: Response, settings: Settings, value: str) -> None:
    """Adjunta la cookie endurecida al response de login/refresh."""
    response.set_cookie(
        key=refresh_cookie_name(settings),
        value=value,
        max_age=refresh_cookie_max_age(settings),
        httponly=True,
        secure=settings.ENV == "prod",
        samesite="lax",
        path="/",
        domain=None,
    )


def cleared_cookie_header(settings: Settings) -> str:
    """Header `Set-Cookie` que borra el refresh (para respuestas de error)."""
    secure = "; Secure" if settings.ENV == "prod" else ""
    return f"{refresh_cookie_name(settings)}=; Max-Age=0; Path=/; HttpOnly; SameSite=lax{secure}"


def clear_refresh_cookie(response: Response, settings: Settings) -> None:
    """Borra la cookie en el response de logout."""
    response.delete_cookie(
        key=refresh_cookie_name(settings),
        path="/",
        domain=None,
        httponly=True,
        secure=settings.ENV == "prod",
        samesite="lax",
    )
