"""Capacidad de agenda en minutos (C-13, D4): plantilla activa menos bloqueos.

Función pura: recibe filas ya cargadas y devuelve minutos por profesional y por
sillón. Usa la plantilla **vigente** (no reconstruye cambios de horario pasados).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.modules.agenda.availability import RuleWindow


@dataclass(frozen=True, slots=True)
class RuleCapacity:
    """Franja semanal de un par profesional-sillón."""

    professional_id: uuid.UUID
    chair_id: uuid.UUID
    window: RuleWindow


@dataclass(frozen=True, slots=True)
class BlockSpan:
    """Bloqueo vigente: alcanza al profesional, al sillón o a ambos."""

    professional_id: uuid.UUID | None
    chair_id: uuid.UUID | None
    starts_at: datetime
    ends_at: datetime


def _minutes_free(start: datetime, end: datetime, blocks: list[BlockSpan]) -> float:
    """Minutos de `[start, end)` que no cubre ningún bloqueo (los solapes se unen)."""
    recortes = sorted(
        (max(b.starts_at, start), min(b.ends_at, end)) for b in blocks if b.ends_at > start
    )
    cubierto = timedelta()
    actual_ini: datetime | None = None
    actual_fin: datetime | None = None
    for ini, fin in recortes:
        if fin <= ini:
            continue
        if actual_fin is None or ini > actual_fin:
            if actual_ini is not None and actual_fin is not None:
                cubierto += actual_fin - actual_ini
            actual_ini, actual_fin = ini, fin
        else:
            actual_fin = max(actual_fin, fin)
    if actual_ini is not None and actual_fin is not None:
        cubierto += actual_fin - actual_ini
    return ((end - start) - cubierto).total_seconds() / 60


def capacity_minutes(
    rules: list[RuleCapacity],
    blocks: list[BlockSpan],
    first_day: date,
    last_day: date,
    tz: ZoneInfo,
) -> tuple[dict[uuid.UUID, int], dict[uuid.UUID, int]]:
    """Minutos de capacidad `(por profesional, por sillón)` entre dos días locales."""
    por_profesional: dict[uuid.UUID, float] = defaultdict(float)
    por_sillon: dict[uuid.UUID, float] = defaultdict(float)
    for regla in rules:
        aplican = [
            b
            for b in blocks
            if b.professional_id == regla.professional_id or b.chair_id == regla.chair_id
        ]
        dia = first_day
        while dia <= last_day:
            if regla.window.applies_to(dia):
                inicio = datetime.combine(dia, regla.window.start_time, tzinfo=tz)
                fin = datetime.combine(dia, regla.window.end_time, tzinfo=tz)
                libre = _minutes_free(inicio, fin, aplican)
                por_profesional[regla.professional_id] += libre
                por_sillon[regla.chair_id] += libre
            dia += timedelta(days=1)
    return (
        {k: round(v) for k, v in por_profesional.items()},
        {k: round(v) for k, v in por_sillon.items()},
    )


__all__ = ["BlockSpan", "RuleCapacity", "capacity_minutes"]
