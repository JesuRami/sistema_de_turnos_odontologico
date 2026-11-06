"""Procesamiento del webhook de WhatsApp (C-10, D5–D7; spec whatsapp-webhook).

El router ya verificó la firma. Acá se interpreta el sobre y cada evento (estado de un mensaje
saliente o mensaje entrante del paciente) se aplica en SU PROPIA transacción:

- un evento que ya se aplicó no vuelve a tener efecto (deduplicación por la base);
- un error inesperado revierte solo ese evento y hace que la respuesta sea 500, para que Meta
  reintente el lote: lo ya aplicado se descarta por la deduplicación.

El webhook nunca llama a Meta: las respuestas al paciente van al outbox que despacha el worker.

Regla 13: los logs llevan solo códigos y contadores; nunca teléfono, texto ni ids del paciente.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from functools import partial

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import Settings
from app.modules.notifications.payload import InboundMessage, MetaWebhook, StatusEvent

logger = logging.getLogger("notifications.webhook")


def parse_webhook(body: bytes) -> MetaWebhook | None:
    """Sobre validado o `None` si el payload (ya firmado) no tiene la estructura mínima."""
    try:
        return MetaWebhook.model_validate_json(body)
    except ValidationError:
        logger.warning("webhook_payload_invalid")
        return None


class WhatsAppWebhookService:
    """Aplica los eventos de un webhook firmado, uno por transacción."""

    def __init__(self, session: AsyncSession, settings: Settings, now: datetime) -> None:
        self.session = session
        self.settings = settings
        self.now = now

    async def process(self, webhook: MetaWebhook) -> bool:
        """Aplica todos los eventos; `False` si alguno falló y conviene que Meta reintente."""
        ok = True
        for entry in webhook.entry:
            for change in entry.changes:
                numero = change.value.metadata.phone_number_id
                for status in change.value.statuses:
                    ok &= await self._safely(partial(self.handle_status, status), "status")
                for message in change.value.messages:
                    ok &= await self._safely(
                        partial(self.handle_message, numero, message), "message"
                    )
        return ok

    async def _safely(self, efecto: Callable[[], Awaitable[None]], tipo: str) -> bool:
        try:
            await efecto()
            await self.session.commit()
        except Exception as exc:  # noqa: BLE001 — un evento no frena a los demás
            await self.session.rollback()
            logger.error("webhook_event_failed tipo=%s error=%s", tipo, type(exc).__name__)
            return False
        return True

    async def handle_status(self, status: StatusEvent) -> None:
        """Estado de un mensaje saliente (D6). Se implementa en `statuses.py`."""
        from app.modules.notifications.statuses import apply_status

        await apply_status(self.session, status, now=self.now)

    async def handle_message(self, phone_number_id: str, message: InboundMessage) -> None:
        """Mensaje entrante del paciente (D7). Se implementa en `inbound.py`."""
        from app.modules.notifications.inbound import apply_inbound

        await apply_inbound(self.session, self.settings, phone_number_id, message, now=self.now)
