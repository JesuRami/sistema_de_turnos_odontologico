"""Selección de proveedores por canal según los settings (C-09, D10).

`disabled` deja el canal fuera del diccionario: el worker no reclama sus jobs y nunca los marca
enviados. El valor `meta` de WhatsApp lo agrega C-10 con el adaptador de la Cloud API.
"""

from __future__ import annotations

from app.core.settings import Settings
from app.models import ReminderChannel
from app.modules.reminders.senders.base import ReminderSender
from app.modules.reminders.senders.fake import FakeSender
from app.modules.reminders.senders.smtp import SmtpSender


def build_senders(settings: Settings) -> dict[ReminderChannel, ReminderSender]:
    senders: dict[ReminderChannel, ReminderSender] = {}
    if settings.REMINDER_WHATSAPP_PROVIDER == "fake":
        senders[ReminderChannel.WHATSAPP] = FakeSender(ReminderChannel.WHATSAPP)
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
