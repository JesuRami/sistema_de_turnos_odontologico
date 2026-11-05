"""Ventana de 24 h de Meta (RN-WA-03, C-09 D5).

Todo recordatorio proactivo sale como plantilla aprobada. Solo dentro de las 24 h posteriores a un
mensaje ENTRANTE del paciente se admite un seguimiento libre (para responderle). C-09 no tiene
mensajes entrantes (los trae C-10), así que siempre pasa `None`; la elección queda lista y probada.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

MessageKind = Literal["template", "session"]
WINDOW = timedelta(hours=24)


def choose_message_kind(last_inbound_at: datetime | None, now: datetime) -> MessageKind:
    if last_inbound_at is not None and timedelta(0) <= now - last_inbound_at < WINDOW:
        return "session"
    return "template"
