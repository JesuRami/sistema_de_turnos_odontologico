"""Webhook de la WhatsApp Cloud API (C-10, D5). Fino: verificación, firma, tamaño y traducción HTTP.

- `GET /webhooks/whatsapp`: handshake de suscripción de Meta (`hub.*`), 403 ante cualquier
  diferencia o parámetro desconocido.
- `POST /webhooks/whatsapp`: cuerpo crudo con tope de tamaño (413), firma `X-Hub-Signature-256`
  verificada antes de parsear (401 + registro sin PII), sobre de Meta y un evento por transacción
  en `WhatsAppWebhookService`. 200 siempre que no haya que reintentar; 500 si un evento falló
  por un error inesperado (Meta reintenta el lote y la deduplicación descarta lo ya aplicado).

Este path está fuera del rate-limit global (`app.main`): la firma es la autenticación y un 429
haría que Meta reintente en ráfaga. Nada de este módulo loguea cuerpo, IP ni encabezados.

C-14 (D5): solo las **firmas inválidas** consumen un cupo por IP
(`WEBHOOK_INVALID_SIGNATURE_RATE_LIMIT`); agotado, el POST responde `429` sin verificar la firma.
Un envío legítimo de Meta nunca consume cupo. Redis caído no bloquea: la firma se sigue exigiendo.
"""

from __future__ import annotations

import hmac
import logging
import re
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.clock import get_now
from app.common.exceptions import DomainError
from app.common.request_meta import client_ip
from app.core.deps import get_db
from app.core.rate_limit import hit, parse_window_spec
from app.core.redis import get_redis
from app.core.settings import Settings, get_settings
from app.modules.notifications.service import WhatsAppWebhookService, parse_webhook
from app.modules.notifications.signature import verify_signature

logger = logging.getLogger("notifications.webhook")

WEBHOOK_PATH = "/webhooks/whatsapp"
router = APIRouter(prefix=WEBHOOK_PATH, tags=["webhooks"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
Now = Annotated[datetime, Depends(get_now)]
RedisDep = Annotated[Redis, Depends(get_redis)]

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


def invalid_signature_key(ip: str) -> str:
    return f"rl:webhook:badsig:ip:{ip}"


async def _over_bad_signature_budget(redis: Redis, ip: str, limit: int) -> int | None:
    """Segundos a esperar si la IP agotó su cupo de firmas inválidas; `None` si puede seguir."""
    try:
        clave = invalid_signature_key(ip)
        usados = await redis.get(clave)
        if usados is not None and int(usados) >= limit:
            ttl = int(await redis.ttl(clave))
            return ttl if ttl > 0 else 1
    except (RedisError, ValueError):
        return None
    return None


@router.post("")
async def receive_events(
    request: Request, session: DbSession, settings: SettingsDep, now: Now, redis: RedisDep
) -> JSONResponse:
    limite, ventana = parse_window_spec(settings.WEBHOOK_INVALID_SIGNATURE_RATE_LIMIT)
    ip = client_ip(request)
    espera = await _over_bad_signature_budget(redis, ip, limite)
    if espera is not None:
        raise DomainError(429, "rate_limited", headers={"Retry-After": str(espera)})
    cuerpo = await _read_limited(request, settings.WHATSAPP_WEBHOOK_MAX_BYTES)
    firma = request.headers.get("x-hub-signature-256")
    if not verify_signature(settings.META_APP_SECRET.get_secret_value(), cuerpo, firma):
        logger.warning("webhook_signature_invalid")
        try:
            await hit(redis, invalid_signature_key(ip), limite, ventana)
        except RedisError:
            pass
        raise DomainError(401, "invalid_signature")
    webhook = parse_webhook(cuerpo)
    if webhook is None:
        return JSONResponse({"status": "ignored"})
    if not await WhatsAppWebhookService(session, settings, now).process(webhook):
        return JSONResponse({"detail": "retry"}, status_code=500)
    return JSONResponse({"status": "ok"})
