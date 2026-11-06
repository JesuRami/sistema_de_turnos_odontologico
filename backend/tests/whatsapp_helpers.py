"""Payloads sintéticos del webhook de WhatsApp y su firma (C-10).

Siguen la forma documentada de la Cloud API (ver notas de `tasks.md` §0.2). Todos los números,
ids y textos son ficticios (regla 13).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from typing import Any

from app.core.settings import Settings

APP_SECRET = "secreto-de-app-ficticio-para-tests-0001"
VERIFY_TOKEN = "verify-token-ficticio-0001"
SHARED_NUMBER = "100000000000009"
WEBHOOK = "/webhooks/whatsapp"


def whatsapp_settings(settings: Settings, **cambios: Any) -> Settings:
    """Settings con secreto de app, token de verificación y número compartido de prueba."""
    from pydantic import SecretStr

    from tests.reminder_helpers import SECRETO_LINKS

    valores: dict[str, Any] = {
        "META_APP_SECRET": SecretStr(APP_SECRET),
        "META_VERIFY_TOKEN": SecretStr(VERIFY_TOKEN),
        "META_PHONE_NUMBER_ID": SHARED_NUMBER,
        "MANAGE_LINK_SECRET": SecretStr(SECRETO_LINKS),
    }
    valores.update(cambios)
    return settings.model_copy(update=valores)


def sign(body: bytes, secret: str = APP_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def encode(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()


def signed_headers(body: bytes, secret: str = APP_SECRET) -> dict[str, str]:
    return {"X-Hub-Signature-256": sign(body, secret), "Content-Type": "application/json"}


def envelope(
    *,
    phone_number_id: str = SHARED_NUMBER,
    statuses: list[dict[str, Any]] | None = None,
    messages: list[dict[str, Any]] | None = None,
    contacts: list[dict[str, Any]] | None = None,
    field: str = "messages",
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "5491100000000", "phone_number_id": phone_number_id},
    }
    if statuses is not None:
        value["statuses"] = statuses
    if messages is not None:
        value["messages"] = messages
        value["contacts"] = contacts or [
            {"profile": {"name": "Nombre Ficticio"}, "wa_id": messages[0]["from"]}
        ]
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "999000000000001", "changes": [{"field": field, "value": value}]}],
    }


def ts(moment: datetime) -> str:
    return str(int(moment.timestamp()))


def status(
    message_id: str, state: str, moment: datetime, *, error_code: int | None = None
) -> dict[str, Any]:
    fila: dict[str, Any] = {
        "id": message_id,
        "status": state,
        "timestamp": ts(moment),
        "recipient_id": "5491155550199",
    }
    if error_code is not None:
        fila["errors"] = [{"code": error_code, "title": "Error ficticio"}]
    return fila


def text_message(
    wa_id: str,
    body: str,
    moment: datetime,
    *,
    message_id: str,
    context_id: str | None = None,
) -> dict[str, Any]:
    fila: dict[str, Any] = {
        "from": wa_id,
        "id": message_id,
        "timestamp": ts(moment),
        "type": "text",
        "text": {"body": body},
    }
    if context_id is not None:
        fila["context"] = {"from": SHARED_NUMBER, "id": context_id}
    return fila


def button_message(
    wa_id: str,
    payload: str,
    moment: datetime,
    *,
    message_id: str,
    context_id: str | None = None,
) -> dict[str, Any]:
    fila: dict[str, Any] = {
        "from": wa_id,
        "id": message_id,
        "timestamp": ts(moment),
        "type": "button",
        "button": {"payload": payload, "text": payload.capitalize()},
    }
    if context_id is not None:
        fila["context"] = {"from": SHARED_NUMBER, "id": context_id}
    return fila
