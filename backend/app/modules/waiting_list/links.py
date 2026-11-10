"""Link firmado y sin estado de una oferta de la lista de espera (C-12, D6; spec offer-link).

Mismo esquema que el link de gestión de C-09 (`reminders/links.py`) con otro prefijo y otro
contexto de firma, así una credencial de oferta nunca sirve como link de gestión ni al revés:

    token = "w1." + base64url( offer_id[16] ‖ HMAC-SHA256(secret, "waitlist-offer/v1" ‖ id)[:16] )

El worker arma el link sin guardar nada (no hay token en claro que recuperar). Rotar
`MANAGE_LINK_SECRET` invalida también los links de oferta vivos.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
import uuid

from app.core.settings import Settings
from app.modules.reminders.links import ManageLinkDisabled

VERSION = "w1"
_CONTEXT = b"waitlist-offer/v1"
_MAC_BYTES = 16
OFFER_TOKEN_RE = re.compile(r"^w1\.[A-Za-z0-9_-]{43}$")


def _mac(secret: str, offer_id: uuid.UUID) -> bytes:
    return hmac.new(secret.encode("utf-8"), _CONTEXT + offer_id.bytes, hashlib.sha256).digest()[
        :_MAC_BYTES
    ]


def sign_offer_token(secret: str, offer_id: uuid.UUID) -> str:
    if not secret:
        raise ManageLinkDisabled("MANAGE_LINK_SECRET no está configurado")
    cuerpo = offer_id.bytes + _mac(secret, offer_id)
    return f"{VERSION}." + base64.urlsafe_b64encode(cuerpo).rstrip(b"=").decode("ascii")


def verify_offer_token(secret: str, token: str) -> uuid.UUID | None:
    """Id de la oferta si la firma es válida y canónica; `None` ante cualquier otra cosa."""
    if not secret or not OFFER_TOKEN_RE.match(token):
        return None
    try:
        cuerpo = base64.urlsafe_b64decode(token[len(VERSION) + 1 :] + "=")
    except (binascii.Error, ValueError):
        return None
    if len(cuerpo) != 16 + _MAC_BYTES:
        return None
    offer_id = uuid.UUID(bytes=cuerpo[:16])
    if not hmac.compare_digest(cuerpo[16:], _mac(secret, offer_id)):
        return None
    if sign_offer_token(secret, offer_id) != token:
        return None
    return offer_id


def build_offer_url(settings: Settings, offer_id: uuid.UUID) -> str:
    """`{FRONTEND_PUBLIC_URL}/o/{token}` con la credencial firmada de la oferta."""
    token = sign_offer_token(settings.MANAGE_LINK_SECRET.get_secret_value(), offer_id)
    return f"{settings.FRONTEND_PUBLIC_URL.rstrip('/')}/o/{token}"
