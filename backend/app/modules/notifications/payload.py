"""Modelos del payload del webhook de la WhatsApp Cloud API (C-10, D2).

EXCEPCIÓN DOCUMENTADA A LA REGLA DURA 2 (decisión del usuario, 2026-11-06; ver AGENTS.md y
CLAUDE.md): estos modelos usan `extra="ignore"` en lugar de `extra="forbid"`, porque Meta agrega
campos a sus payloads sin aviso y un 4xx por un campo desconocido haría que Meta reintente y
termine desactivando la suscripción. Condiciones de la excepción:

1. Solo se parsea con estos modelos DESPUÉS de verificar `X-Hub-Signature-256`.
2. Los campos que el sistema consume siguen tipados y validados; lo ignorado nunca se persiste ni
   se loguea.
3. Ningún otro borde del repo se relaja (lo verifica `tests/test_edges.py`).

Un payload firmado que no valida la estructura mínima se responde 200 y se registra como
`webhook_payload_invalid` (sin PII), para que Meta no lo reintente.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Regla 2 — excepción D2: solo para el payload de Meta (ver docstring del módulo).
_META = ConfigDict(extra="ignore", populate_by_name=True, frozen=True)

_EPOCH = r"^[0-9]{1,12}$"


class MetaError(BaseModel):
    model_config = _META

    code: int


class StatusEvent(BaseModel):
    """Cambio de estado de un mensaje saliente (`sent`, `delivered`, `read`, `failed`…)."""

    model_config = _META

    id: str = Field(min_length=1, max_length=256)
    status: str = Field(min_length=1, max_length=32)
    timestamp: str = Field(pattern=_EPOCH)
    errors: list[MetaError] = Field(default_factory=list)


class TextBody(BaseModel):
    model_config = _META

    body: str = Field(max_length=4096)


class ButtonBody(BaseModel):
    """Respuesta a un botón `quick_reply` de una plantilla."""

    model_config = _META

    payload: str | None = Field(default=None, max_length=256)
    text: str | None = Field(default=None, max_length=256)


class ButtonReply(BaseModel):
    model_config = _META

    id: str = Field(max_length=256)


class InteractiveBody(BaseModel):
    model_config = _META

    type: str
    button_reply: ButtonReply | None = None


class MessageContext(BaseModel):
    """Mensaje al que responde el paciente (su `id` es el `provider_message_id` del job)."""

    model_config = _META

    id: str | None = Field(default=None, max_length=256)


class InboundMessage(BaseModel):
    """Mensaje entrante del paciente. `from_` es su `wa_id` (dígitos, sin `+`)."""

    model_config = _META

    from_: str = Field(alias="from", pattern=r"^[0-9]{6,20}$")
    id: str = Field(min_length=1, max_length=256)
    timestamp: str = Field(pattern=_EPOCH)
    type: str = Field(min_length=1, max_length=32)
    text: TextBody | None = None
    button: ButtonBody | None = None
    interactive: InteractiveBody | None = None
    context: MessageContext | None = None


class Metadata(BaseModel):
    model_config = _META

    phone_number_id: str = Field(pattern=r"^[0-9]{1,32}$")


class ChangeValue(BaseModel):
    model_config = _META

    metadata: Metadata
    statuses: list[StatusEvent] = Field(default_factory=list)
    messages: list[InboundMessage] = Field(default_factory=list)


class Change(BaseModel):
    model_config = _META

    # Solo se maneja `messages`; cualquier otro tipo de cambio invalida el payload (200 sin efecto).
    field: Literal["messages"]
    value: ChangeValue


class Entry(BaseModel):
    model_config = _META

    changes: list[Change]


class MetaWebhook(BaseModel):
    """Sobre del webhook (`object = whatsapp_business_account`)."""

    model_config = _META

    object: Literal["whatsapp_business_account"]
    entry: list[Entry] = Field(min_length=1)
