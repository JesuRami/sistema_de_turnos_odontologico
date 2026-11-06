"""Adaptador de la Cloud API de Meta (C-10, D4; spec whatsapp-channel).

La API de Meta es HTTP externo: se simula con `httpx.MockTransport` (la regla 9 prohíbe mocks de
la base, no de un proveedor externo). Todos los teléfonos y tokens son ficticios.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

import httpx
import pytest
from app.models import ReminderChannel
from app.modules.reminders.senders.base import OutboundMessage, SendError
from app.modules.reminders.senders.meta import MetaWhatsAppSender

TOKEN = "token-ficticio-de-acceso-0001"
TELEFONO = "+5491155550111"
SENDER_ID = "100000000000001"
BASE = "https://graph.example.test"


def _mensaje(**overrides: object) -> OutboundMessage:
    valores: dict[str, object] = {
        "channel": ReminderChannel.WHATSAPP,
        "to": TELEFONO,
        "template_name": "recordatorio_24h_v1",
        "locale": "es_AR",
        "params": {
            "hora": "15:30",
            "profesional": "Dra. Ficticia",
            "clinica": "Clínica Ficticia",
            "link": "http://localhost:5173/g/v1.ficticio",
        },
        "body": "cuerpo renderizado",
        "sender_id": SENDER_ID,
        "param_order": ("hora", "profesional", "clinica", "link"),
        "buttons": ("confirm", "change"),
    }
    valores.update(overrides)
    return OutboundMessage(**valores)  # type: ignore[arg-type]


def _sender(handler: Callable[[httpx.Request], httpx.Response]) -> MetaWhatsAppSender:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return MetaWhatsAppSender(
        client=client, token=TOKEN, base_url=BASE, api_version="v19.0", timeout_s=5
    )


def _ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "messaging_product": "whatsapp",
            "contacts": [{"input": TELEFONO, "wa_id": "5491155550111"}],
            "messages": [{"id": "wamid.FICTICIO-OK"}],
        },
    )


def _error(status: int, code: int) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            json={
                "error": {
                    "message": f"Recipient {TELEFONO} is not a WhatsApp user",
                    "type": "OAuthException",
                    "code": code,
                    "fbtrace_id": "ficticio",
                }
            },
        )

    return handler


async def test_envio_de_plantilla_arma_el_request_de_meta() -> None:
    capturados: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        capturados.append(request)
        return _ok(request)

    resultado = await _sender(handler).send(_mensaje())

    assert resultado.provider_message_id == "wamid.FICTICIO-OK"
    (request,) = capturados
    assert str(request.url) == f"{BASE}/v19.0/{SENDER_ID}/messages"
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    cuerpo = json.loads(request.content)
    assert cuerpo["messaging_product"] == "whatsapp"
    assert cuerpo["to"] == "5491155550111"
    assert cuerpo["type"] == "template"
    plantilla = cuerpo["template"]
    assert plantilla["name"] == "recordatorio_24h_v1"
    assert plantilla["language"] == {"code": "es_AR"}
    body, *botones = plantilla["components"]
    assert body == {
        "type": "body",
        "parameters": [
            {"type": "text", "text": "15:30"},
            {"type": "text", "text": "Dra. Ficticia"},
            {"type": "text", "text": "Clínica Ficticia"},
            {"type": "text", "text": "http://localhost:5173/g/v1.ficticio"},
        ],
    }
    assert botones == [
        {
            "type": "button",
            "sub_type": "quick_reply",
            "index": "0",
            "parameters": [{"type": "payload", "payload": "confirm"}],
        },
        {
            "type": "button",
            "sub_type": "quick_reply",
            "index": "1",
            "parameters": [{"type": "payload", "payload": "change"}],
        },
    ]


async def test_send_text_arma_un_mensaje_de_sesion() -> None:
    capturados: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        capturados.append(request)
        return _ok(request)

    resultado = await _sender(handler).send_text(SENDER_ID, TELEFONO, "Listo, confirmado.")

    assert resultado.provider_message_id == "wamid.FICTICIO-OK"
    cuerpo = json.loads(capturados[0].content)
    assert cuerpo == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "5491155550111",
        "type": "text",
        "text": {"preview_url": False, "body": "Listo, confirmado."},
    }


async def test_sin_sender_id_no_envia() -> None:
    with pytest.raises(SendError) as exc_info:
        await _sender(_ok).send(_mensaje(sender_id=None))

    assert exc_info.value.code == "no_sender_id"
    assert exc_info.value.retryable is False


@pytest.mark.parametrize(
    ("status", "code", "esperado", "reintentable"),
    [
        (500, 1, "http_5xx", True),
        (503, 2, "http_5xx", True),
        (429, 130429, "meta_130429", True),
        (400, 131056, "meta_131056", True),
        (400, 4, "meta_4", True),
        (401, 190, "meta_190", True),
        (403, 131005, "meta_131005", True),
        (400, 131026, "meta_131026", False),
        (400, 132001, "meta_132001", False),
        (400, 131008, "meta_131008", False),
        (400, 131047, "meta_131047", False),
        (400, 100, "meta_100", False),
    ],
)
async def test_errores_de_meta_clasificados(
    status: int, code: int, esperado: str, reintentable: bool, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)

    with pytest.raises(SendError) as exc_info:
        await _sender(_error(status, code)).send(_mensaje())

    error = exc_info.value
    assert error.code == esperado
    assert error.retryable is reintentable
    texto = str(error) + repr(error) + caplog.text
    assert TELEFONO not in texto
    assert "5491155550111" not in texto
    assert TOKEN not in texto


async def test_error_sin_cuerpo_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html>bad gateway</html>")

    with pytest.raises(SendError) as exc_info:
        await _sender(handler).send(_mensaje())

    assert (exc_info.value.code, exc_info.value.retryable) == ("http_5xx", True)


async def test_timeout_es_reintentable(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    with pytest.raises(SendError) as exc_info:
        await _sender(handler).send(_mensaje())

    assert (exc_info.value.code, exc_info.value.retryable) == ("timeout", True)
    assert TOKEN not in caplog.text


async def test_error_de_red_es_reintentable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin red", request=request)

    with pytest.raises(SendError) as exc_info:
        await _sender(handler).send(_mensaje())

    assert (exc_info.value.code, exc_info.value.retryable) == ("network", True)


async def test_respuesta_ok_sin_id_es_reintentable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"messages": []})

    with pytest.raises(SendError) as exc_info:
        await _sender(handler).send(_mensaje())

    assert (exc_info.value.code, exc_info.value.retryable) == ("meta_no_id", True)


def test_repr_del_mensaje_no_expone_datos() -> None:
    texto = repr(_mensaje())

    assert TELEFONO not in texto and "Clínica" not in texto


async def test_build_senders_con_meta_usa_el_adaptador_y_se_cierra() -> None:
    from app.core.settings import Settings
    from app.modules.reminders.senders import build_senders, close_senders

    settings = Settings.model_validate(
        {
            "DATABASE_URL": "postgresql+asyncpg://turnos:clave@localhost:5432/turnos_test",
            "REDIS_URL": "redis://localhost:6379/0",
            "JWT_SECRET": "s" * 32,
            "REMINDER_WHATSAPP_PROVIDER": "meta",
            "WHATSAPP_TOKEN": TOKEN,
            "META_APP_SECRET": "secreto-ficticio-de-app-0001",
            "META_PHONE_NUMBER_ID": SENDER_ID,
            "META_VERIFY_TOKEN": "verify-ficticio-0001",
        }
    )
    senders = build_senders(settings)

    sender = senders[ReminderChannel.WHATSAPP]
    assert isinstance(sender, MetaWhatsAppSender)
    assert TOKEN not in repr(sender)
    await close_senders(senders)
