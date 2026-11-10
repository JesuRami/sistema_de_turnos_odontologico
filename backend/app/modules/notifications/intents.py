"""Intención de la respuesta del paciente (C-10, D7; spec whatsapp-webhook).

Función pura sobre el mensaje ya parseado. Los botones de respuesta rápida se reconocen por su
payload (`confirm`, `change`, `cancel`, ver `reminders.templates`). El texto se normaliza (sin
mayúsculas, tildes ni signos, espacios colapsados) y debe coincidir COMPLETO con una frase de las
listas cerradas: así "si no puedo" no confirma. La baja se evalúa primero ("no me escriban" no es
un "no").
"""

from __future__ import annotations

import re
import unicodedata

from app.models import WhatsAppIntent
from app.modules.notifications.payload import InboundMessage
from app.modules.reminders.templates import (
    BUTTON_CANCEL,
    BUTTON_CHANGE,
    BUTTON_CONFIRM,
    BUTTON_OFFER_ACCEPT,
    BUTTON_OFFER_DECLINE,
)

_STOP = frozenset(
    {
        "stop",
        "baja",
        "darme de baja",
        "dar de baja",
        "desuscribir",
        "desuscribirme",
        "no me escriban",
        "no me escriban mas",
        "no quiero mas",
        "no quiero mas mensajes",
        "no me manden mas",
        "no me manden mas mensajes",
    }
)
_CONFIRM = frozenset(
    {"si", "confirmo", "confirmar", "ok si", "si confirmo", "confirmado", "si confirmar"}
)
_CHANGE = frozenset(
    {
        "no",
        "reprogramar",
        "cambiar",
        "cancelar",
        "no puedo",
        "cambiar turno",
        "cancelar turno",
        "reprogramar turno",
    }
)
# C-12 (D8): respuesta a una oferta de la lista de espera. Solo actúan si citan la oferta.
_ACCEPT_OFFER = frozenset({"tomarlo", "lo tomo", "lo quiero", "tomar"})
_DECLINE_OFFER = frozenset({"paso", "no me sirve"})
_BUTTONS = {
    BUTTON_CONFIRM: WhatsAppIntent.CONFIRM,
    BUTTON_CHANGE: WhatsAppIntent.CHANGE,
    BUTTON_CANCEL: WhatsAppIntent.CHANGE,
    BUTTON_OFFER_ACCEPT: WhatsAppIntent.ACCEPT_OFFER,
    BUTTON_OFFER_DECLINE: WhatsAppIntent.DECLINE_OFFER,
}
_NO_ALNUM = re.compile(r"[^a-z0-9 ]+")
_SPACES = re.compile(r"\s+")


def normalize(texto: str) -> str:
    """Minúsculas, sin tildes ni signos, espacios colapsados."""
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFKD", texto.lower()) if not unicodedata.combining(c)
    )
    return _SPACES.sub(" ", _NO_ALNUM.sub(" ", sin_tildes)).strip()


def classify(message: InboundMessage) -> WhatsAppIntent:
    if message.type == "button" and message.button is not None:
        return _BUTTONS.get(message.button.payload or "", WhatsAppIntent.UNKNOWN)
    if (
        message.type == "interactive"
        and message.interactive is not None
        and message.interactive.button_reply is not None
    ):
        return _BUTTONS.get(message.interactive.button_reply.id, WhatsAppIntent.UNKNOWN)
    if message.type != "text" or message.text is None:
        return WhatsAppIntent.UNKNOWN
    frase = normalize(message.text.body)
    if frase in _STOP:
        return WhatsAppIntent.STOP
    if frase in _CONFIRM:
        return WhatsAppIntent.CONFIRM
    if frase in _CHANGE:
        return WhatsAppIntent.CHANGE
    if frase in _ACCEPT_OFFER:
        return WhatsAppIntent.ACCEPT_OFFER
    if frase in _DECLINE_OFFER:
        return WhatsAppIntent.DECLINE_OFFER
    return WhatsAppIntent.UNKNOWN
