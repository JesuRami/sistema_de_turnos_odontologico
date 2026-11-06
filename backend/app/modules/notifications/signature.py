"""Firma `X-Hub-Signature-256` del webhook de Meta (C-10, D5; spec whatsapp-webhook).

Meta firma el cuerpo crudo con HMAC-SHA256 y el secreto de la app. La comparación es en tiempo
constante y se hace sobre los bytes exactos recibidos, ANTES de interpretar nada del cuerpo.
"""

from __future__ import annotations

import hashlib
import hmac

_PREFIX = "sha256="


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    """`True` solo si hay secreto, el encabezado es `sha256=<hex>` y coincide con el cuerpo."""
    if not secret or not header or not header.startswith(_PREFIX):
        return False
    esperado = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, header[len(_PREFIX) :].strip().lower())
