"""Normalización de teléfonos a E.164 (región default AR, sin filtrar el dato en errores)."""

import pytest
from app.common.phone import InvalidPhoneError, normalize_phone_e164

CELULAR_FICTICIO = "+5491155550123"


@pytest.mark.parametrize(
    "raw",
    [
        "011 15 5555-0123",  # nacional con prefijo 0 y 15
        "+54 9 11 5555-0123",  # internacional con espacios
        "+54-9-11-5555-0123",  # internacional con guiones
        "+5491155550123",  # ya en E.164
    ],
)
def test_formatos_equivalentes_normalizan_igual(raw: str) -> None:
    assert normalize_phone_e164(raw) == CELULAR_FICTICIO


def test_fijo_ficticio_normaliza_a_54_sin_9() -> None:
    assert normalize_phone_e164("011 4555-0123") == "+541145550123"


def test_region_parametrizable_para_numero_nacional_extranjero() -> None:
    # Número ficticio uruguayo (región UY) en formato nacional.
    assert normalize_phone_e164("099 123 456", region="UY") == "+59899123456"


@pytest.mark.parametrize("raw", ["12ab", "12345", "", "   ", "+99 123"])
def test_numero_invalido_rechazado_sin_filtrar_el_valor(raw: str) -> None:
    with pytest.raises(InvalidPhoneError) as exc:
        normalize_phone_e164(raw)
    mensaje = str(exc.value)
    assert mensaje != ""
    if raw.strip():
        assert raw not in mensaje
        assert "12" not in mensaje
