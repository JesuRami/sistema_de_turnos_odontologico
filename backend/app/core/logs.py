"""Logging estructurado sin PII (C-14, D2; regla dura 13).

Solo stdlib a propósito: lo usan la API, el worker y las herramientas de `app.ops` sin
arrastrar dependencias. `configure_logging` instala en el root un único handler con:

- `ContextFilter`: suma `request_id`/`clinic_id` del request en curso.
- `JsonFormatter` (una línea JSON por registro) o `TextFormatter` (desarrollo), que enmascaran
  teléfonos, emails, DNI, JWT/bearer y tokens de gestión/oferta en el mensaje, los `extra` y el
  texto de la excepción (asyncpg incluye `Key (phone_e164)=(+54…)` en el detalle de un
  `IntegrityError`).

Cada registro lleva `request_id` (y `clinic_id` si el request lo fijó) desde `ContextVar`s:
el middleware de contexto los setea al entrar y los limpia al salir.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, Literal

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
clinic_id_var: ContextVar[str | None] = ContextVar("clinic_id", default=None)

LogFormat = Literal["json", "text"]

# --------------------------------------------------------------------------- redacción

# Orden importa: primero lo más específico (JWT, bearer, tokens), después emails, teléfonos y DNI.
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}")
# Credenciales firmadas de los links (`m1.`/`w1.` + base64url) y tokens opacos largos de C-07/C-08.
_LINK_TOKEN_RE = re.compile(r"\b[a-z]\d\.[A-Za-z0-9_-]{16,}")
_OPAQUE_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{40,}(?![A-Za-z0-9_-])")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
# Teléfonos: `+` opcional y al menos 8 dígitos con separadores comunes (espacio, guion, punto,
# paréntesis). Se evalúa antes que el DNI porque un celular AR tiene 10+ dígitos.
_PHONE_RE = re.compile(r"(?<![\w.])\+?\d[\d\s().-]{6,}\d(?![\w])")
_DNI_DOTTED_RE = re.compile(r"\b\d{1,2}\.\d{3}\.\d{3}\b")
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ][\d:.+\-Z]*)?")


def _mask_phone(match: re.Match[str]) -> str:
    digitos = re.sub(r"\D", "", match.group(0))
    if len(digitos) < 8:
        return match.group(0)
    prefijo = "+" if match.group(0).lstrip().startswith("+") else ""
    return f"{prefijo}{digitos[:2]}{'*' * (len(digitos) - 4)}{digitos[-2:]}"


def _protect(text: str, pattern: re.Pattern[str], store: list[str]) -> str:
    """Reemplaza `pattern` por marcadores para que el enmascarado de teléfonos no lo toque."""

    def _guardar(match: re.Match[str]) -> str:
        store.append(match.group(0))
        return f"\x00{len(store) - 1}\x00"

    return pattern.sub(_guardar, text)


def _restore(text: str, store: list[str]) -> str:
    return re.sub(r"\x00(\d+)\x00", lambda m: store[int(m.group(1))], text)


def redact(text: str) -> str:
    """Enmascara PII y secretos en un texto libre (mensaje de log o de excepción)."""
    if not text:
        return text
    salida = _BEARER_RE.sub("Bearer [redacted]", text)
    salida = _JWT_RE.sub("[jwt]", salida)
    salida = _LINK_TOKEN_RE.sub("[token]", salida)
    salida = _EMAIL_RE.sub(lambda m: f"***@{m.group(1)}", salida)
    # UUIDs y fechas ISO no son PII y tienen muchos dígitos: se protegen del enmascarado.
    guardados: list[str] = []
    salida = _protect(salida, _UUID_RE, guardados)
    salida = _protect(salida, _ISO_DATE_RE, guardados)
    salida = _OPAQUE_TOKEN_RE.sub("[token]", salida)
    salida = _DNI_DOTTED_RE.sub("[dni]", salida)
    salida = _PHONE_RE.sub(_mask_phone, salida)
    # DNI sin puntos (7-8 dígitos sueltos) que no llegó a ser teléfono.
    salida = re.sub(r"(?<![\w*])\d{7,8}(?![\w*])", "[dni]", salida)
    return _restore(salida, guardados)


def redact_value(value: Any) -> Any:
    """Redacta strings (también dentro de listas/dicts); el resto pasa tal cual."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact_value(v) for v in value]
    return value


_RESERVED = frozenset(
    vars(logging.LogRecord("x", logging.INFO, "x", 0, "", None, None)).keys()
    | {"message", "asctime", "request_id", "clinic_id"}
)


class ContextFilter(logging.Filter):
    """Agrega `request_id`/`clinic_id` del request en curso (no toca el mensaje)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        record.clinic_id = clinic_id_var.get()
        return True


def _message(record: logging.LogRecord) -> str:
    try:
        return record.getMessage()
    except Exception:  # noqa: BLE001 - un log mal formado no debe tirar el request
        return str(record.msg)


def _extras(record: logging.LogRecord) -> dict[str, Any]:
    return {
        clave: redact_value(valor)
        for clave, valor in vars(record).items()
        if clave not in _RESERVED and not clave.startswith("_")
    }


class JsonFormatter(logging.Formatter):
    """Una línea JSON por registro, **redactada** (D2).

    La redacción vive en el formatter y no en un filtro: el `LogRecord` es compartido por todos
    los handlers y mutarlo cambiaría lo que ven otros (p. ej. `caplog`).
    """

    def format(self, record: logging.LogRecord) -> str:
        cuerpo: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(_message(record)),
        }
        for clave in ("request_id", "clinic_id"):
            valor = getattr(record, clave, None)
            if valor is not None:
                cuerpo[clave] = valor
        cuerpo.update(_extras(record))
        if record.exc_info:
            cuerpo["exc"] = redact(self.formatException(record.exc_info))
        elif record.exc_text:
            cuerpo["exc"] = redact(record.exc_text)
        return json.dumps(cuerpo, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """Formato legible para desarrollo (`LOG_FORMAT=text`), también redactado."""

    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "request_id"):
            record.request_id = request_id_var.get()
        extras = _extras(record)
        texto = super().format(record)
        if extras:
            texto += " " + json.dumps(extras, ensure_ascii=False, default=str)
        return redact(texto)


_HANDLER_NAME = "turnos-redacted"


def build_handler(fmt: LogFormat = "json") -> logging.Handler:
    handler = logging.StreamHandler(sys.stdout)
    handler.set_name(_HANDLER_NAME)
    handler.addFilter(ContextFilter())
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    return handler


def configure_logging(level: str = "INFO", fmt: LogFormat = "json") -> None:
    """Instala el handler redactado en el root (idempotente) y alinea uvicorn con él.

    Los loggers de uvicorn se redirigen al root: su `access log` imprime el path real (que en
    `/api/manage/{token}` lleva el token), así que se apaga y lo reemplaza el log de acceso del
    middleware de contexto, que usa la plantilla de la ruta.
    """
    root = logging.getLogger()
    for existente in list(root.handlers):
        if existente.get_name() == _HANDLER_NAME:
            root.removeHandler(existente)
    root.addHandler(build_handler(fmt))
    root.setLevel(level.upper())
    for nombre in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(nombre)
        lg.handlers.clear()
        lg.propagate = True
    acceso = logging.getLogger("uvicorn.access")
    acceso.handlers.clear()
    acceso.propagate = False
    acceso.disabled = True
