"""Link de gestión firmado y sin estado para los mensajes (C-09, D9).

La base solo guarda el SHA-256 del token aleatorio de C-07, y un turno de recepción no tiene
token: el motor no puede recuperar uno en claro para escribir `{{link}}`. Este segundo formato
de credencial lo reconstruye sin guardar nada:

    token = "v1." + base64url( id[16] ‖ HMAC-SHA256(secret, "manage-link/v1" ‖ id)[:16] )

`GET/PATCH /api/manage/{token}` lo acepta además del token aleatorio, con las mismas guardas (TTL
absoluto, vista mínima, ventana de cancelación, 404 uniforme, rate-limit por `sha256(token)`).
Rotar `MANAGE_LINK_SECRET` invalida los links firmados vivos. El punto `.` no está en el alfabeto
del token aleatorio, así que los dos formatos no pueden confundirse.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
import uuid

from app.core.settings import Settings

VERSION = "v1"
_CONTEXT = b"manage-link/v1"
_MAC_BYTES = 16
SIGNED_RE = re.compile(r"^v1\.[A-Za-z0-9_-]{43}$")


class ManageLinkDisabled(RuntimeError):
    """`MANAGE_LINK_SECRET` vacío (solo permitido con ENV=dev): no hay links firmados."""


def _mac(secret: str, appointment_id: uuid.UUID) -> bytes:
    return hmac.new(
        secret.encode("utf-8"), _CONTEXT + appointment_id.bytes, hashlib.sha256
    ).digest()[:_MAC_BYTES]


def sign_manage_token(secret: str, appointment_id: uuid.UUID) -> str:
    """Token firmado del turno; estable, así cada mensaje del turno lleva el mismo link."""
    if not secret:
        raise ManageLinkDisabled("MANAGE_LINK_SECRET no está configurado")
    cuerpo = appointment_id.bytes + _mac(secret, appointment_id)
    return f"{VERSION}." + base64.urlsafe_b64encode(cuerpo).rstrip(b"=").decode("ascii")


def verify_manage_token(secret: str, token: str) -> uuid.UUID | None:
    """Id del turno si la firma es válida; `None` ante cualquier otra cosa (sin distinguir)."""
    if not secret or not SIGNED_RE.match(token):
        return None
    try:
        cuerpo = base64.urlsafe_b64decode(token[len(VERSION) + 1 :] + "=")
    except (binascii.Error, ValueError):
        return None
    if len(cuerpo) != 16 + _MAC_BYTES:
        return None
    appointment_id = uuid.UUID(bytes=cuerpo[:16])
    if not hmac.compare_digest(cuerpo[16:], _mac(secret, appointment_id)):
        return None
    # Forma canónica: el último carácter de 32 bytes en base64url lleva 2 bits de relleno, así que
    # cambiarlo daría OTRA cadena para el mismo token. Se rechaza para que cada credencial tenga
    # una sola representación (si no, el cupo por `sha256(token)` se esquivaría con 4 variantes).
    if sign_manage_token(secret, appointment_id) != token:
        return None
    return appointment_id


def build_manage_url(settings: Settings, appointment_id: uuid.UUID) -> str:
    """`{FRONTEND_PUBLIC_URL}/g/{token}` con el token firmado del turno."""
    token = sign_manage_token(settings.MANAGE_LINK_SECRET.get_secret_value(), appointment_id)
    return f"{settings.FRONTEND_PUBLIC_URL.rstrip('/')}/g/{token}"
