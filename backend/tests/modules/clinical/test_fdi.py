"""Numeración FDI (C-15, spec `clinical/odontogram`): unit puro, sin base.

Fuente independiente: ISO 3950 / FDI — permanentes cuadrantes 1–4 con piezas 1–8; temporales
cuadrantes 5–8 con piezas 1–5. Escenarios "Pieza permanente/temporal válida" y "Códigos fuera de
rango".
"""

from __future__ import annotations

import pytest
from app.modules.clinical.fdi import (
    DECIDUOUS_TEETH,
    PERMANENT_TEETH,
    SURFACE_LABELS,
    dentition_of,
    is_anterior,
    is_valid_tooth,
    surface_label,
)


@pytest.mark.parametrize("tooth", [11, 18, 21, 28, 31, 38, 41, 48, 36, 13])
def test_permanentes_validas(tooth: int) -> None:
    assert is_valid_tooth(tooth)
    assert dentition_of(tooth) == "permanent"


@pytest.mark.parametrize("tooth", [51, 55, 61, 65, 71, 75, 81, 85])
def test_temporales_validas(tooth: int) -> None:
    assert is_valid_tooth(tooth)
    assert dentition_of(tooth) == "deciduous"


@pytest.mark.parametrize("tooth", [0, 9, 10, 19, 20, 49, 50, 56, 66, 76, 86, 90, 99, 100, -11])
def test_fuera_de_rango(tooth: int) -> None:
    assert not is_valid_tooth(tooth)
    with pytest.raises(ValueError):
        dentition_of(tooth)


def test_denticiones_completas() -> None:
    assert len(PERMANENT_TEETH) == 32
    assert len(DECIDUOUS_TEETH) == 20
    assert PERMANENT_TEETH[:8] == (11, 12, 13, 14, 15, 16, 17, 18)
    assert DECIDUOUS_TEETH[-5:] == (81, 82, 83, 84, 85)
    assert set(PERMANENT_TEETH).isdisjoint(DECIDUOUS_TEETH)


@pytest.mark.parametrize(
    ("tooth", "anterior"),
    [(11, True), (13, True), (14, False), (36, False), (43, True), (53, True), (54, False)],
)
def test_anteriores_y_posteriores(tooth: int, anterior: bool) -> None:
    assert is_anterior(tooth) is anterior


def test_tabla_de_caras() -> None:
    assert set(SURFACE_LABELS) == {"M", "D", "O", "V", "L", "W"}
    assert surface_label(36, "O") == "oclusal"
    assert surface_label(11, "O") == "incisal"
    assert surface_label(36, "M") == "mesial"
    assert surface_label(36, "W") == "pieza completa"


def test_nombre_mostrado_saneado() -> None:
    from app.modules.clinical.attachments import sanitize_display_name

    assert sanitize_display_name("../../etc/passwd\n.png") == "passwd.png"
    assert (
        sanitize_display_name("C:" + chr(92) + "x" + chr(92) + "rx" + chr(0) + ".pdf") == "rx.pdf"
    )
    assert sanitize_display_name("") == "archivo"
