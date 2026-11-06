"""Adaptador de la WhatsApp Cloud API de Meta (C-10, D4; RN-WA-02).

Único canal WhatsApp soportado: `POST {base}/{version}/{phone_number_id}/messages` con `Bearer`.
Los recordatorios salen como plantilla (`type=template`, `es_AR`) con parámetros posicionales en
el orden que declara el catálogo y botones de respuesta rápida con payload; las respuestas a un
mensaje entrante salen como texto de sesión (`type=text`).

Regla 13: ni el teléfono, ni el token, ni el cuerpo de error de Meta (que suele repetir el número)
llegan a un log o a `SendError`: de la respuesta de error solo se lee el código numérico.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.models import ReminderChannel
from app.modules.reminders.senders.base import OutboundMessage, SendError, SendResult

logger = logging.getLogger("reminders.meta")

# Códigos de Meta que se resuelven solos o arreglando la configuración: se reintentan.
# Tasa/caída (4, 80007, 130429, 131056) y credencial/permiso (190, 131005).
_RETRYABLE_CODES = frozenset({4, 80007, 130429, 131056, 190, 131005})


def _wa_id(e164: str) -> str:
    """Meta espera el número sin `+`."""
    return e164.removeprefix("+")


def _error_code(response: httpx.Response) -> int | None:
    try:
        datos = response.json()
    except ValueError:
        return None
    error = datos.get("error") if isinstance(datos, dict) else None
    codigo = error.get("code") if isinstance(error, dict) else None
    return codigo if isinstance(codigo, int) else None


def _classify(response: httpx.Response) -> SendError:
    """`SendError` con un código estable; nunca incluye el mensaje de Meta."""
    codigo = _error_code(response)
    if response.status_code >= 500 and (codigo is None or codigo not in _RETRYABLE_CODES):
        return SendError("http_5xx", retryable=True)
    if codigo is None:
        return SendError(f"http_{response.status_code}", retryable=response.status_code == 429)
    return SendError(f"meta_{codigo}", retryable=codigo in _RETRYABLE_CODES)


class MetaWhatsAppSender:
    """`ReminderSender` de WhatsApp sobre la Cloud API; también envía textos de sesión."""

    channel = ReminderChannel.WHATSAPP

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        token: str,
        base_url: str,
        api_version: str,
        timeout_s: float,
    ) -> None:
        self._client = client
        self._token = token
        self._base = base_url.rstrip("/")
        self._version = api_version
        self._timeout = timeout_s

    def __repr__(self) -> str:  # el token nunca en un repr
        return f"MetaWhatsAppSender(version={self._version})"

    async def aclose(self) -> None:
        await self._client.aclose()

    async def send(self, message: OutboundMessage) -> SendResult:
        componentes: list[dict[str, Any]] = [
            {
                "type": "body",
                "parameters": [
                    {"type": "text", "text": message.params[nombre]}
                    for nombre in message.param_order
                ],
            }
        ]
        componentes.extend(
            {
                "type": "button",
                "sub_type": "quick_reply",
                "index": str(indice),
                "parameters": [{"type": "payload", "payload": payload}],
            }
            for indice, payload in enumerate(message.buttons)
        )
        cuerpo = {
            "messaging_product": "whatsapp",
            "to": _wa_id(message.to),
            "type": "template",
            "template": {
                "name": message.template_name,
                "language": {"code": message.locale},
                "components": componentes,
            },
        }
        return await self._post(message.sender_id, cuerpo)

    async def send_text(self, sender_id: str, to: str, body: str) -> SendResult:
        cuerpo = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": _wa_id(to),
            "type": "text",
            "text": {"preview_url": False, "body": body},
        }
        return await self._post(sender_id, cuerpo)

    async def _post(self, sender_id: str | None, cuerpo: dict[str, Any]) -> SendResult:
        if not sender_id:
            raise SendError("no_sender_id", retryable=False)
        url = f"{self._base}/{self._version}/{sender_id}/messages"
        try:
            response = await self._client.post(
                url,
                json=cuerpo,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=self._timeout,
            )
        except httpx.TimeoutException:
            raise SendError("timeout", retryable=True) from None
        except httpx.HTTPError:
            raise SendError("network", retryable=True) from None
        if response.is_success:
            try:
                datos = response.json()
                provider_id = datos["messages"][0]["id"]
            except (ValueError, KeyError, IndexError, TypeError):
                raise SendError("meta_no_id", retryable=True) from None
            if not isinstance(provider_id, str) or not provider_id:
                raise SendError("meta_no_id", retryable=True)
            return SendResult(provider_message_id=provider_id)
        error = _classify(response)
        logger.warning("Meta rechazó un envío (%s, reintentable=%s)", error.code, error.retryable)
        raise error
