"""Totales y formato de importes de presupuestos (C-15, D8): unit puro."""

from __future__ import annotations

import pytest
from app.common.exceptions import DomainError
from app.modules.clinical.plans import BIGINT_MAX, format_ars, phase_totals


def test_subtotales_y_total_del_escenario_de_la_spec() -> None:
    fases, total = phase_totals([(1, 2, 15000), (1, 1, 5000), (2, 1, 80000)])

    assert fases == {1: 35000, 2: 80000}
    assert total == 115000


@pytest.mark.parametrize(
    ("centavos", "texto"),
    [(115000, "1.150,00"), (0, "0,00"), (5, "0,05"), (123456789, "1.234.567,89")],
)
def test_formato_es_ar(centavos: int, texto: str) -> None:
    assert format_ars(centavos) == texto


def test_desbordamiento_de_bigint() -> None:
    with pytest.raises(DomainError) as exc:
        phase_totals([(1, 2, BIGINT_MAX // 2 + 1)])

    assert (exc.value.status_code, exc.value.detail) == (422, "amount_too_large")
