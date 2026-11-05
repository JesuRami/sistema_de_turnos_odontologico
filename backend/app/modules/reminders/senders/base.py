"""Puerto de envío por canal (C-09, D10): contrato que cumplen el fake, el SMTP y, en C-10, Meta.

`OutboundMessage` lleva el destinatario y el cuerpo, o sea datos personales: su `repr`/`str`
nunca los muestra (regla 13), así un log o un traceback que lo incluya no filtra nada. Del mismo
modo `SendError` expone solo un código (`timeout`, `rejected`…), jamás el mensaje del proveedor,
que suele traer el teléfono o el email.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from app.models import ReminderChannel


@dataclass(frozen=True, slots=True, repr=False)
class OutboundMessage:
    """Un mensaje listo para enviar por un canal."""

    channel: ReminderChannel
    to: str
    template_name: str
    locale: str
    params: Mapping[str, str]
    body: str
    subject: str | None = None

    def __repr__(self) -> str:
        return f"OutboundMessage(channel={self.channel.value}, template={self.template_name})"


@dataclass(frozen=True, slots=True)
class SendResult:
    """Resultado de un envío aceptado por el proveedor."""

    provider_message_id: str


class SendError(Exception):
    """Fallo de envío con un código estable y si conviene reintentar."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class ReminderSender(Protocol):
    """Envía mensajes de un canal; lanza `SendError` ante cualquier falla."""

    channel: ReminderChannel

    async def send(self, message: OutboundMessage) -> SendResult: ...
