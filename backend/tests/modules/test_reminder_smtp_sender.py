"""Adaptador SMTP contra un servidor real local `aiosmtpd`, sin mocks (C-09, D10)."""

from __future__ import annotations

import socket
from collections.abc import Iterator
from email import message_from_bytes
from email.message import Message
from typing import Any

import pytest
from aiosmtpd.controller import Controller
from aiosmtpd.smtp import SMTP, Envelope, Session
from app.models import ReminderChannel
from app.modules.reminders.senders.base import OutboundMessage, SendError
from app.modules.reminders.senders.smtp import SmtpSender

DESTINO = "paciente.ficticia@example.com"
RECHAZADO = "no.existe.ficticio@example.com"
REMITENTE = "turnos@example.com"


class Capturador:
    """Handler que guarda lo recibido y rechaza lo configurado."""

    def __init__(self) -> None:
        self.recibidos: list[Envelope] = []
        self.respuesta_data = "250 OK"

    async def handle_RCPT(
        self, server: SMTP, session: Session, envelope: Envelope, address: str, rcpt_options: Any
    ) -> str:
        if address == RECHAZADO:
            return "550 5.1.1 buzón inexistente"
        envelope.rcpt_tos.append(address)
        return "250 OK"

    async def handle_DATA(self, server: SMTP, session: Session, envelope: Envelope) -> str:
        if self.respuesta_data.startswith("250"):
            self.recibidos.append(envelope)
        return self.respuesta_data


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture()
def servidor() -> Iterator[tuple[Capturador, int]]:
    capturador = Capturador()
    puerto = _puerto_libre()
    controller = Controller(capturador, hostname="127.0.0.1", port=puerto)
    controller.start()
    try:
        yield capturador, puerto
    finally:
        controller.stop()


def _sender(puerto: int) -> SmtpSender:
    return SmtpSender(host="127.0.0.1", port=puerto, user="", password="", sender=REMITENTE)


def _mensaje(destino: str = DESTINO) -> OutboundMessage:
    return OutboundMessage(
        channel=ReminderChannel.EMAIL,
        to=destino,
        template_name="email_recordatorio_24h_v1",
        locale="es_AR",
        params={},
        body="Hola María, mañana a las 15:30 tenés turno. Gestionalo: https://x.example.com/g/t",
        subject="Recordatorio de tu turno",
    )


async def test_el_correo_llega_con_asunto_cuerpo_y_remitente(
    servidor: tuple[Capturador, int],
) -> None:
    capturador, puerto = servidor

    resultado = await _sender(puerto).send(_mensaje())

    [sobre] = capturador.recibidos
    assert sobre.mail_from == REMITENTE
    assert sobre.rcpt_tos == [DESTINO]
    correo: Message = message_from_bytes(sobre.content)  # type: ignore[arg-type]
    assert correo["Subject"] == "Recordatorio de tu turno"
    assert correo["From"] == REMITENTE and correo["To"] == DESTINO
    cuerpo = correo.get_payload(decode=True)
    assert isinstance(cuerpo, bytes)
    assert "mañana a las 15:30" in cuerpo.decode("utf-8")
    assert resultado.provider_message_id.startswith("<") and resultado.provider_message_id.endswith(
        ">"
    )
    assert correo["Message-ID"] == resultado.provider_message_id


async def test_sin_servidor_es_un_error_transitorio_sin_la_direccion() -> None:
    puerto = _puerto_libre()  # nadie escucha

    with pytest.raises(SendError) as exc_info:
        await _sender(puerto).send(_mensaje())

    error = exc_info.value
    assert (error.code, error.retryable) == ("connection_error", True)
    assert DESTINO not in str(error) and DESTINO not in repr(error)
    assert error.__cause__ is None and error.__suppress_context__ is True


async def test_destinatario_rechazado_es_permanente_y_no_filtra_la_direccion(
    servidor: tuple[Capturador, int],
) -> None:
    _, puerto = servidor

    with pytest.raises(SendError) as exc_info:
        await _sender(puerto).send(_mensaje(RECHAZADO))

    error = exc_info.value
    assert (error.code, error.retryable) == ("recipient_rejected", False)
    assert RECHAZADO not in str(error) and RECHAZADO not in repr(error)


@pytest.mark.parametrize(
    ("respuesta", "reintentable"),
    [("451 4.3.0 probá más tarde", True), ("554 5.7.1 contenido rechazado", False)],
)
async def test_el_codigo_smtp_decide_si_se_reintenta(
    servidor: tuple[Capturador, int], respuesta: str, reintentable: bool
) -> None:
    capturador, puerto = servidor
    capturador.respuesta_data = respuesta

    with pytest.raises(SendError) as exc_info:
        await _sender(puerto).send(_mensaje())

    assert exc_info.value.code == "smtp_rejected"
    assert exc_info.value.retryable is reintentable
    assert capturador.recibidos == []


def test_el_repr_del_adaptador_no_muestra_credenciales() -> None:
    sender = SmtpSender(
        host="smtp.example.com",
        port=587,
        user="usuario",
        password="clave-ficticia",
        sender=REMITENTE,
    )

    assert "clave-ficticia" not in repr(sender) and "usuario" not in repr(sender)
