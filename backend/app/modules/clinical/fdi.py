"""Numeración dental FDI (ISO 3950) y caras (C-15, spec `clinical/odontogram`).

Permanentes: cuadrantes 1–4, piezas 1–8 (11–48). Temporales: cuadrantes 5–8, piezas 1–5
(51–85). La dentición se deriva del código. La misma regla está en la base como CHECK
(`app.models.clinical_common.fdi_tooth_sql`).
"""

from __future__ import annotations

from typing import Literal

Dentition = Literal["permanent", "deciduous"]

PERMANENT_TEETH: tuple[int, ...] = tuple(q * 10 + p for q in (1, 2, 3, 4) for p in range(1, 9))
DECIDUOUS_TEETH: tuple[int, ...] = tuple(q * 10 + p for q in (5, 6, 7, 8) for p in range(1, 6))
_VALID = frozenset(PERMANENT_TEETH) | frozenset(DECIDUOUS_TEETH)

SURFACE_LABELS: dict[str, str] = {
    "M": "mesial",
    "D": "distal",
    "O": "oclusal",
    "V": "vestibular",
    "L": "lingual",
    "W": "pieza completa",
}


def is_valid_tooth(tooth: int) -> bool:
    return tooth in _VALID


def dentition_of(tooth: int) -> Dentition:
    if tooth in PERMANENT_TEETH:
        return "permanent"
    if tooth in DECIDUOUS_TEETH:
        return "deciduous"
    raise ValueError("pieza FDI inválida")


def teeth_of(dentition: Dentition) -> tuple[int, ...]:
    return PERMANENT_TEETH if dentition == "permanent" else DECIDUOUS_TEETH


def is_anterior(tooth: int) -> bool:
    """Incisivos y caninos (posiciones 1–3): su cara `O` es incisal."""
    if not is_valid_tooth(tooth):
        raise ValueError("pieza FDI inválida")
    return tooth % 10 <= 3


def surface_label(tooth: int, surface: str) -> str:
    if surface == "O" and is_anterior(tooth):
        return "incisal"
    return SURFACE_LABELS[surface]
