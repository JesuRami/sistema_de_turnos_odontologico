"""Webhook de la WhatsApp Cloud API (C-10, D5). Fino: verificación, firma, tamaño y traducción HTTP.

- `GET /webhooks/whatsapp`: handshake de suscripción de Meta (`hub.*`), 403 ante cualquier
  diferencia o parámetro desconocido.
- `POST /webhooks/whatsapp`: cuerpo crudo con tope de tamaño (413), firma `X-Hub-Signature-256`
  verificada antes de parsear (401 + registro sin PII), sobre de Meta y un evento por transacción
  en `WhatsAppWebhookService`. 200 siempre que no haya que reintentar; 500 si un evento falló
  por un error inesperado (Meta reintenta el lote y la deduplicación descarta lo ya aplicado).

Este path está fuera del rate-limit global (`app.main`): la firma es la autenticación y un 429
haría que Meta reintente en ráfaga. Nada de este módulo loguea cuerpo, IP ni encabezados.
"""

from __future__ import annotations

import hmac
import logging
import re
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.clock import get_now
from app.common.exceptions import DomainError
from app.core.deps import get_db
from app.core.settings import Settings, get_settings
from app.modules.notifications.service import WhatsAppWebhookService, parse_webhook
from app.modules.notifications.signature import verify_signature

logger = logging.getLogger("notifications.webhook")

WEBHOOK_PATH = "/webhooks/whatsapp"
router = APIRouter(prefix=WEBHOOK_PATH, tags=["webhooks"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
Now = Annotated[datetime, Depends(get_now)]

_VERIFY_PARAMS = frozenset({"hub.mode", "hub.verify_token", "hub.challenge"})
_CHALLENGE_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


@router.get("", response_class=PlainTextResponse)
async def verify_subscription(request: Request, settings: SettingsDep) -> PlainTextResponse:
    """Devuelve `hub.challenge` solo si el modo y el token de verificación coinciden."""
    params = request.query_params
    esperado = settings.META_VERIFY_TOKEN.get_secret_value()
    recibido = params.get("hub.verify_token", "")
    challenge = params.get("hub.challenge", "")
    valido = (
        bool(esperado)
        and not set(params) - _VERIFY_PARAMS
        and params.get("hub.mode") == "subscribe"
        and hmac.compare_digest(esperado.encode(), recibido.encode())
        and bool(_CHALLENGE_RE.match(challenge))
    )
    if not valido:
        raise DomainError(403, "webhook_verification_failed")
    return PlainTextResponse(challenge)


async def _read_limited(request: Request, limite: int) -> bytes:
    """Cuerpo crudo; corta con 413 apenas supera `limite` (sin leer el resto)."""
    declarado = request.headers.get("content-length")
    if declarado is not None and declarado.isdigit() and int(declarado) > limite:
        raise DomainError(413, "payload_too_large")
    partes: list[bytes] = []
    total = 0
    async for parte in request.stream():
        total += len(parte)
        if total > limite:
            raise DomainError(413, "payload_too_large")
        partes.append(parte)
    return b"".join(partes)


@router.post("")
async def receive_events(
    request: Request, session: DbSession, settings: SettingsDep, now: Now
) -> JSONResponse:
    cuerpo = await _read_limited(request, settings.WHATSAPP_WEBHOOK_MAX_BYTES)
    firma = request.headers.get("x-hub-signature-256")
    if not verify_signature(settings.META_APP_SECRET.get_secret_value(), cuerpo, firma):
        logger.warning("webhook_signature_invalid")
        raise DomainError(401, "invalid_signature")
    webhook = parse_webhook(cuerpo)
    if webhook is None:
        return JSONResponse({"status": "ignored"})
    if not await WhatsAppWebhookService(session, settings, now).process(webhook):
        return JSONResponse({"detail": "retry"}, status_code=500)
    return JSONResponse({"status": "ok"})
