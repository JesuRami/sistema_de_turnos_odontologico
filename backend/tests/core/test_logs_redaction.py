"""Logs estructurados sin PII (C-14, D2; regla dura 13). Puro: sin red ni base.

Los tests son síncronos a propósito (corren igual con o sin `pytest-asyncio`).
"""

from __future__ import annotations

import io
import json
import logging

import pytest
from app.core.logs import (
    JsonFormatter,
    TextFormatter,
    build_handler,
    configure_logging,
    redact,
    request_id_var,
)

TELEFONO = "+5491155550111"
EMAIL = "persona.ficticia@example.com"


@pytest.mark.parametrize(
    ("entrada", "no_debe_quedar"),
    [
        (f"tel={TELEFONO}", "55550111"),
        ("llamar al 011 15 5555-0123", "5555-0123"),
        (f"mail {EMAIL}", "persona.ficticia"),
        ("dni 30.123.456", "30.123.456"),
        ("dni 30123456", "30123456"),
        ("Authorization: Bearer abc.def.ghi", "abc.def.ghi"),
        ("jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJh", "eyJhbGci"),
        ("link w1.AbCdEfGhIjKlMnOpQrStUv_-123", "AbCdEfGhIjKl"),
        (f"Key (phone_e164)=({TELEFONO}) already exists.", "55550111"),
    ],
)
def test_redact_enmascara_pii_y_secretos(entrada: str, no_debe_quedar: str) -> None:
    assert no_debe_quedar not in redact(entrada)


def test_redact_conserva_uuid_fechas_y_numeros_cortos() -> None:
    texto = "turno 3f2b8c1e-1234-4abc-9def-0123456789ab 2030-01-07T11:00:00+00:00 status 409"
    assert redact(texto) == texto


def test_redact_deja_pista_util_del_telefono() -> None:
    enmascarado = redact(f"tel {TELEFONO}")
    assert enmascarado.startswith("tel +54")
    assert enmascarado.endswith("11")


def _record(msg: str, *args: object, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, msg, args, None)
    for clave, valor in extra.items():
        setattr(record, clave, valor)
    return record


def test_json_formatter_redacta_mensaje_args_y_extra() -> None:
    linea = JsonFormatter().format(
        _record("alta tel=%s", TELEFONO, route="/api/manage/{token}", note=f"avisar a {EMAIL}")
    )
    cuerpo = json.loads(linea)

    assert "55550111" not in linea and "persona.ficticia" not in linea
    assert cuerpo["route"] == "/api/manage/{token}"
    assert cuerpo["level"] == "INFO"


def test_json_formatter_redacta_la_traza_de_la_excepcion() -> None:
    try:
        raise ValueError(f"Key (phone_e164)=({TELEFONO}) already exists")
    except ValueError:
        import sys

        record = logging.LogRecord("t", logging.ERROR, __file__, 1, "boom", None, sys.exc_info())
    linea = JsonFormatter().format(record)

    assert "ValueError" in linea
    assert "55550111" not in linea


def test_el_formatter_no_muta_el_record_compartido() -> None:
    """Otros handlers (p. ej. `caplog`) siguen viendo el mensaje original."""
    record = _record("tel=%s", TELEFONO)
    JsonFormatter().format(record)
    assert record.getMessage() == f"tel={TELEFONO}"


def test_text_formatter_tambien_redacta() -> None:
    assert "55550111" not in TextFormatter().format(_record("tel=%s", TELEFONO))


def test_handler_agrega_request_id_del_contexto() -> None:
    salida = io.StringIO()
    handler = build_handler("json")
    handler.stream = salida  # type: ignore[attr-defined]
    logger = logging.getLogger("test.logs.request_id")
    logger.addHandler(handler)
    logger.propagate = False
    token = request_id_var.set("req-ficticio-0001")
    try:
        logger.warning("hola")
    finally:
        request_id_var.reset(token)
        logger.removeHandler(handler)

    assert json.loads(salida.getvalue())["request_id"] == "req-ficticio-0001"


def test_configure_logging_es_idempotente_y_apaga_el_access_log_de_uvicorn() -> None:
    configure_logging("INFO", "json")
    configure_logging("INFO", "json")

    propios = [h for h in logging.getLogger().handlers if h.get_name() == "turnos-redacted"]
    assert len(propios) == 1
    # El access log de uvicorn imprime el path real (con el token de gestión): queda apagado.
    assert logging.getLogger("uvicorn.access").disabled is True
