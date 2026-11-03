"""Cálculo de horarios libres (C-05 D8): función pura, sin DB ni reloj propio.

La grilla se arma en la zona de la clínica (RN-GL-03): `start_time + k·slot`
de cada regla vigente, en hora local de pared. Un horario local inexistente por
cambio de horario se omite. El fin del turno se calcula en tiempo absoluto y
debe caer dentro de la franja local. Contrato: C-07 la reutiliza para la
disponibilidad pública.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

Interval = tuple[datetime, datetime]

DEFAULT_ALTERNATIVES = 3
DEFAULT_HORIZON = timedelta(days=14)


@dataclass(frozen=True, slots=True)
class RuleWindow:
    """Franja semanal de un par profesional-sillón (proyección de `schedule_rule`)."""

    weekday: int
    start_time: time
    end_time: time
    slot_duration_min: int
    valid_from: date
    valid_to: date | None

    def applies_to(self, day: date) -> bool:
        return (
            day.weekday() == self.weekday
            and self.valid_from <= day
            and (self.valid_to is None or day <= self.valid_to)
        )


@dataclass(frozen=True, slots=True)
class Slot:
    """Horario libre `[starts_at, ends_at)` (UTC-aware)."""

    starts_at: datetime
    ends_at: datetime


def localize(day: date, wall: time, tz: ZoneInfo) -> datetime | None:
    """`day + wall` en `tz`, o `None` si esa hora local no existe (salto de horario)."""
    naive = datetime.combine(day, wall)
    aware = naive.replace(tzinfo=tz)
    if aware.astimezone(UTC).astimezone(tz).replace(tzinfo=None) != naive:
        return None
    return aware


def _intersects(start: datetime, end: datetime, intervals: Sequence[Interval]) -> bool:
    return any(a < end and start < b for a, b in intervals)


def _day_candidates(
    rule: RuleWindow, day: date, tz: ZoneInfo, duration: timedelta
) -> list[datetime]:
    candidatos: list[datetime] = []
    paso = timedelta(minutes=rule.slot_duration_min)
    fin_franja = datetime.combine(day, rule.end_time)
    pared = datetime.combine(day, rule.start_time)
    while pared + duration <= fin_franja:
        inicio = localize(day, pared.time(), tz)
        if inicio is not None:
            fin_local = (inicio + duration).astimezone(tz).replace(tzinfo=None)
            if fin_local <= fin_franja:
                candidatos.append(inicio)
        pared += paso
    return candidatos


def suggest_slots(
    rules: Sequence[RuleWindow],
    *,
    blocks: Sequence[Interval],
    busy: Sequence[Interval],
    desde: datetime,
    tz: ZoneInfo,
    duration: timedelta,
    buffer: timedelta,
    now: datetime,
    n: int = DEFAULT_ALTERNATIVES,
    horizon: timedelta = DEFAULT_HORIZON,
) -> list[Slot]:
    """Primeros `n` horarios libres desde `desde` (y no antes de `now`) dentro de `horizon`.

    - `blocks`: rangos bloqueados; el turno `[inicio, fin)` no puede intersectarlos.
    - `busy`: rangos ocupados (con buffer, incluidos sobreturnos); el rango ocupado
      del candidato `[inicio, fin + buffer)` no puede intersectarlos.
    """
    piso = max(desde, now)
    techo = desde + horizon
    resultado: list[Slot] = []
    dia = piso.astimezone(tz).date()
    ultimo = techo.astimezone(tz).date()
    while dia <= ultimo and len(resultado) < n:
        candidatos = sorted(
            {
                inicio
                for rule in rules
                if rule.applies_to(dia)
                for inicio in _day_candidates(rule, dia, tz, duration)
            }
        )
        for inicio in candidatos:
            fin = inicio + duration
            if inicio < piso or inicio >= techo:
                continue
            if _intersects(inicio, fin, blocks) or _intersects(inicio, fin + buffer, busy):
                continue
            resultado.append(Slot(starts_at=inicio.astimezone(UTC), ends_at=fin.astimezone(UTC)))
            if len(resultado) == n:
                break
        dia += timedelta(days=1)
    return resultado
