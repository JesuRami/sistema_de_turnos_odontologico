"""Adaptador SMTP del email de respaldo (C-09, D10): `smtplib` de la biblioteca estándar.

Corre el envío bloqueante en un hilo (`asyncio.to_thread`). Seguridad por puerto: 465 usa TLS
implícito, 587 usa STARTTLS y cualquier otro (p. ej. un servidor local de desarrollo) va en claro.
Las excepciones se traducen a `SendError` con un código fijo: el texto de `smtplib` trae la
dirección del destinatario y no puede llegar a un log, a `last_error` ni a un `delivery_event`.
"""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid

from app.models import ReminderChannel
from app.modules.reminders.senders.base import OutboundMessage, SendError, SendResult

TIMEOUT_S = 10
DEFAULT_SUBJECT = "Tu turno"


class SmtpSender:
    channel = ReminderChannel.EMAIL

    def __init__(self, *, host: str, port: int, user: str, password: str, sender: str) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._from = sender

    def __repr__(self) -> str:
        return f"SmtpSender(host={self._host}, port={self._port})"

    async def send(self, message: OutboundMessage) -> SendResult:
        return await asyncio.to_thread(self._send_sync, message)

    def _send_sync(self, message: OutboundMessage) -> SendResult:
        correo = EmailMessage()
        correo["From"] = self._from
        correo["To"] = message.to
        correo["Subject"] = message.subject or DEFAULT_SUBJECT
        message_id = make_msgid(domain=self._from.rpartition("@")[2] or None)
        correo["Message-ID"] = message_id
        correo.set_content(message.body)
        try:
            with self._connect() as conexion:
                conexion.send_message(correo)
        except smtplib.SMTPRecipientsRefused:
            raise SendError("recipient_rejected", retryable=False) from None
        except smtplib.SMTPAuthenticationError:
            raise SendError("auth_failed", retryable=True) from None
        except smtplib.SMTPResponseException as exc:
            # 5xx es permanente (buzón inexistente, rechazo de contenido); 4xx es transitorio.
            raise SendError("smtp_rejected", retryable=not 500 <= exc.smtp_code < 600) from None
        except (smtplib.SMTPException, OSError):
            raise SendError("connection_error", retryable=True) from None
        return SendResult(provider_message_id=message_id)

    def _connect(self) -> smtplib.SMTP:
        if self._port == 465:
            conexion: smtplib.SMTP = smtplib.SMTP_SSL(
                self._host, self._port, timeout=TIMEOUT_S, context=ssl.create_default_context()
            )
        else:
            conexion = smtplib.SMTP(self._host, self._port, timeout=TIMEOUT_S)
            if self._port == 587:
                conexion.starttls(context=ssl.create_default_context())
        if self._user:
            conexion.login(self._user, self._password)
        return conexion
