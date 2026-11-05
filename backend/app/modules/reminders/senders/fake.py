"""Sender de prueba (C-09, D10): guarda los envíos en memoria y solo loguea metadatos.

Sirve para desarrollo y tests. Nunca registra destinatario, cuerpo ni parámetros (regla 13). Los
fallos simulados se encolan en `failures` y se lanzan en orden, uno por `send`.
"""

from __future__ import annotations

import itertools
import logging

from app.models import ReminderChannel
from app.modules.reminders.senders.base import OutboundMessage, SendError, SendResult

logger = logging.getLogger("reminders.fake")


class FakeSender:
    def __init__(self, channel: ReminderChannel) -> None:
        self.channel = channel
        self.sent: list[OutboundMessage] = []
        self.failures: list[SendError] = []
        self._ids = itertools.count(1)

    async def send(self, message: OutboundMessage) -> SendResult:
        if self.failures:
            raise self.failures.pop(0)
        self.sent.append(message)
        provider_id = f"fake-{next(self._ids)}"
        logger.info(
            "fake %s envío %s (plantilla %s)",
            self.channel.value,
            provider_id,
            message.template_name,
        )
        return SendResult(provider_message_id=provider_id)
