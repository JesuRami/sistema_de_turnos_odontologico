"""Render del mensaje: variables de la plantilla y fecha/hora en formato argentino (C-09, D6/D11).

La zona de la clínica interviene solo acá, al mostrar: los instantes se guardan y comparan en UTC.
Los nombres de día van en español sin depender del locale del sistema operativo.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from zoneinfo import ZoneInfo

_DAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
_VARIABLE = re.compile(r"\{\{(\w+)\}\}")


class MissingVariable(ValueError):
    """Una variable de la plantilla no tiene valor; el mensaje nombra solo la variable."""


def format_date(moment: datetime, tz: ZoneInfo) -> str:
    """`jueves 9/10`: día de la semana, día y mes locales, sin ceros a la izquierda."""
    local = moment.astimezone(tz)
    return f"{_DAYS[local.weekday()]} {local.day}/{local.month}"


def format_time(moment: datetime, tz: ZoneInfo) -> str:
    """`15:30` en la zona de la clínica."""
    return moment.astimezone(tz).strftime("%H:%M")


def render(body: str, params: Mapping[str, str]) -> str:
    """Reemplaza `{{variable}}`; falla si falta alguna en vez de enviar la llave cruda."""
    faltan = sorted({v for v in _VARIABLE.findall(body) if v not in params})
    if faltan:
        raise MissingVariable(f"faltan variables de la plantilla: {', '.join(faltan)}")
    return _VARIABLE.sub(lambda m: params[m.group(1)], body)
