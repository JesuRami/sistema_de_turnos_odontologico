"""Texto libre operativo sin datos personales (regla 13; C-11 D6, C-12 D10).

Notas de recepción y motivos (reenvío manual, prioridad, excepción a FIFO) son cortos y no pueden
llevar teléfono, email ni DNI. El error nunca repite el valor recibido.
"""

from __future__ import annotations

import re

from app.common.exceptions import DomainError

_EMAIL_RE = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
# Secuencias de dígitos con separadores típicos de teléfonos y DNI (`+54 11 5555-0101`,
# `30.123.456`); con 7 dígitos o más se consideran un dato personal.
_DIGITS_RE = re.compile(r"\+?\d[\d\s.\-()/]*\d")
_PII_MIN_DIGITS = 7


def contains_personal_data(texto: str) -> bool:
    """True si el texto parece llevar un email, un teléfono o un DNI."""
    if _EMAIL_RE.search(texto):
        return True
    return any(
        sum(c.isdigit() for c in tramo) >= _PII_MIN_DIGITS for tramo in _DIGITS_RE.findall(texto)
    )


def clean_free_text(
    texto: str | None, *, max_length: int, code: str, min_length: int = 0
) -> str | None:
    """Recorta; vacío → `None`; fuera de largo o con PII → `422 {code}`."""
    if texto is None:
        if min_length:
            raise DomainError(422, code)
        return None
    limpio = texto.strip()
    if not limpio:
        if min_length:
            raise DomainError(422, code)
        return None
    if len(limpio) < min_length or len(limpio) > max_length or contains_personal_data(limpio):
        raise DomainError(422, code)
    return limpio
