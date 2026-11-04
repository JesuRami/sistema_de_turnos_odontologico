"""Serialización CSV/JSON compartida por reportes y exportación (C-13).

- Una celda de texto que empieza con `=`, `+`, `-`, `@`, tab o CR se prefija con
  `'` para que una planilla no la interprete como fórmula (CSV injection).
- Valores del dominio (enums, fechas, UUID, JSON) se llevan a texto estable.
- El CSV sale en UTF-8 con BOM para que Excel respete los acentos.
"""

from __future__ import annotations

import csv
import enum
import io
import json
import uuid
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from typing import Any

from fastapi import Response

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
BOM = "\ufeff"


def neutralize(text: str) -> str:
    """Prefija con `'` el texto que una planilla leería como fórmula."""
    return f"'{text}" if text.startswith(_FORMULA_PREFIXES) else text


def to_json_value(value: Any) -> Any:
    """Valor serializable a JSON (enums por valor, fechas ISO, UUID como texto)."""
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def to_cell(value: Any) -> str | int | float:
    """Valor de una celda CSV; `None` queda vacío y los JSON se serializan ordenados."""
    valor = to_json_value(value)
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, dict | list):
        return neutralize(json.dumps(valor, ensure_ascii=False, sort_keys=True))
    if isinstance(valor, str):
        return neutralize(valor)
    return valor  # type: ignore[no-any-return]


def csv_text(headers: Sequence[str], rows: Iterable[Sequence[Any]], *, header: bool = True) -> str:
    """Texto CSV (sin BOM) con cada celda neutralizada."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    if header:
        writer.writerow(headers)
    for fila in rows:
        writer.writerow([to_cell(v) for v in fila])
    return buffer.getvalue()


def csv_response(filename: str, headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> Response:
    """Respuesta de descarga `text/csv` UTF-8."""
    return Response(
        content=(BOM + csv_text(headers, rows)).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
