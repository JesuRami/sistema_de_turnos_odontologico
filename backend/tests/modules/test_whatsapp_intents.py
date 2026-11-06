"""Clasificación de la respuesta del paciente (C-10, D7; spec whatsapp-webhook).

Unitario puro: la función recibe el mensaje ya parseado y devuelve la intención.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.models import WhatsAppIntent
from app.modules.notifications.intents import classify
from app.modules.notifications.payload import InboundMessage


def _texto(cuerpo: str) -> InboundMessage:
    return InboundMessage.model_validate(
        {
            "from": "5491155550101",
            "id": "wamid.X",
            "timestamp": "1",
            "type": "text",
            "text": {"body": cuerpo},
        }
    )


def _boton(payload: str) -> InboundMessage:
    return InboundMessage.model_validate(
        {
            "from": "5491155550101",
            "id": "wamid.X",
            "timestamp": "1",
            "type": "button",
            "button": {"payload": payload, "text": "x"},
        }
    )


def _otro(tipo: str, **extra: Any) -> InboundMessage:
    return InboundMessage.model_validate(
        {"from": "5491155550101", "id": "wamid.X", "timestamp": "1", "type": tipo, **extra}
    )


@pytest.mark.parametrize(
    "cuerpo", ["Sí!", "si", "SI", "sí", " Si. ", "confirmo", "Confirmar", "si, confirmo", "ok si"]
)
def test_variantes_de_si(cuerpo: str) -> None:
    assert classify(_texto(cuerpo)) is WhatsAppIntent.CONFIRM


@pytest.mark.parametrize(
    "cuerpo", ["NO", "no.", "reprogramar", "Cambiar", "cancelar", "No puedo", "cambiar turno"]
)
def test_variantes_de_cambio(cuerpo: str) -> None:
    assert classify(_texto(cuerpo)) is WhatsAppIntent.CHANGE


@pytest.mark.parametrize(
    "cuerpo",
    [
        "STOP",
        "baja",
        "Baja!",
        "no me escriban más",
        "No me escriban",
        "no quiero más",
        "desuscribir",
    ],
)
def test_baja(cuerpo: str) -> None:
    assert classify(_texto(cuerpo)) is WhatsAppIntent.STOP


@pytest.mark.parametrize(
    "cuerpo", ["si no puedo", "a qué hora era?", "hola", "", "sisi no", "no se"]
)
def test_texto_no_reconocido(cuerpo: str) -> None:
    assert classify(_texto(cuerpo)) is WhatsAppIntent.UNKNOWN


@pytest.mark.parametrize(
    ("payload", "esperado"),
    [
        ("confirm", WhatsAppIntent.CONFIRM),
        ("change", WhatsAppIntent.CHANGE),
        ("cancel", WhatsAppIntent.CHANGE),
        ("otro", WhatsAppIntent.UNKNOWN),
    ],
)
def test_botones(payload: str, esperado: WhatsAppIntent) -> None:
    assert classify(_boton(payload)) is esperado


def test_boton_interactivo() -> None:
    mensaje = _otro(
        "interactive", interactive={"type": "button_reply", "button_reply": {"id": "confirm"}}
    )

    assert classify(mensaje) is WhatsAppIntent.CONFIRM


@pytest.mark.parametrize("tipo", ["image", "audio", "sticker", "location", "reaction"])
def test_otros_tipos_son_desconocidos(tipo: str) -> None:
    assert classify(_otro(tipo)) is WhatsAppIntent.UNKNOWN
