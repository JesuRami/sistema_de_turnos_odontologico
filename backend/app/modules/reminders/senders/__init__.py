"""Selección de proveedores por canal según los settings (C-09, D10).

`disabled` deja el canal fuera del diccionario: el worker no reclama sus jobs y nunca los marca
enviados. `meta` (C-10) usa la Cloud API con un `httpx.AsyncClient` propio, que `close_senders`
cierra al apagar el worker.
"""

from __future__ import annotations

import httpx

from app.core.settings import Settings
from app.models import ReminderChannel
from app.modules.reminders.senders.base import ReminderSender
from app.modules.reminders.senders.fake import FakeSender
from app.modules.reminders.senders.meta import MetaWhatsAppSender
from app.modules.reminders.senders.smtp import SmtpSender


def build_senders(settings: Settings) -> dict[ReminderChannel, ReminderSender]:
    senders: dict[ReminderChannel, ReminderSender] = {}
    if settings.REMINDER_WHATSAPP_PROVIDER == "fake":
        senders[ReminderChannel.WHATSAPP] = FakeSender(ReminderChannel.WHATSAPP)
    elif settings.REMINDER_WHATSAPP_PROVIDER == "meta":
        senders[ReminderChannel.WHATSAPP] = MetaWhatsAppSender(
            client=httpx.AsyncClient(),
            token=settings.WHATSAPP_TOKEN.get_secret_value(),
            base_url=settings.META_GRAPH_BASE_URL,
            api_version=settings.META_API_VERSION,
            timeout_s=settings.WHATSAPP_HTTP_TIMEOUT_S,
        )
    if settings.REMINDER_EMAIL_PROVIDER == "fake":
        senders[ReminderChannel.EMAIL] = FakeSender(ReminderChannel.EMAIL)
    elif settings.REMINDER_EMAIL_PROVIDER == "smtp":
        if not settings.EMAIL_HOST or not settings.EMAIL_FROM:
            raise ValueError(
                "REMINDER_EMAIL_PROVIDER=smtp exige EMAIL_HOST y EMAIL_FROM configurados"
            )
        senders[ReminderChannel.EMAIL] = SmtpSender(
            host=settings.EMAIL_HOST,
            port=settings.EMAIL_PORT,
            user=settings.EMAIL_USER,
            password=settings.EMAIL_PASSWORD,
            sender=settings.EMAIL_FROM,
        )
    return senders


async def close_senders(senders: dict[ReminderChannel, ReminderSender]) -> None:
    """Cierra los clientes HTTP de los proveedores que los tienen (Meta)."""
    for sender in senders.values():
        cerrar = getattr(sender, "aclose", None)
        if cerrar is not None:
            await cerrar()
