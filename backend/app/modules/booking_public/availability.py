"""Disponibilidad pública (C-07, D3): unión por sillón de `suggest_slots`, función pura.

Es la única definición de "hueco ofrecible": la usan la lectura pública, la validación de
grilla de la reserva y los alternativos del `409`. Sin DB ni reloj propio: recibe datos ya
leídos (reglas por sillón, bloqueos y ocupados con su alcance) y el instante `now`.

Alcance de bloqueos y ocupados: `chair_id=None` aplica a todos los sillones (algo del
profesional); un `chair_id` concreto aplica solo a ese sillón (algo de otro profesional en
ese sillón, o un bloqueo del sillón).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.modules.agenda.availability import RuleWindow, suggest_slots

DEFAULT_CAP = 500
_ONE_SECOND = timedelta(seconds=1)


@dataclass(frozen=True, slots=True)
class ChairRules:
    """Reglas semanales vigentes del profesional sobre un sillón activo."""

    chair_id: uuid.UUID
    rules: tuple[RuleWindow, ...]


@dataclass(frozen=True, slots=True)
class Scoped:
    """Intervalo `[starts_at, ends_at)` con alcance (`None` = todos los sillones)."""

    chair_id: uuid.UUID | None
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True, slots=True)
class PublicSlot:
    """Hueco ofrecible `[starts_at, ends_at)` (UTC-aware), sin sillón (RN-ON-01)."""

    starts_at: datetime
    ends_at: datetime


def _by_duration(rules: Sequence[RuleWindow]) -> dict[int, list[RuleWindow]]:
    grupos: dict[int, list[RuleWindow]] = defaultdict(list)
    for rule in rules:
        grupos[rule.slot_duration_min].append(rule)
    return grupos


def _applies(item: Scoped, chair_id: uuid.UUID) -> bool:
    return item.chair_id is None or item.chair_id == chair_id


def public_slots(
    chairs: Sequence[ChairRules],
    *,
    blocks: Sequence[Scoped],
    busy: Sequence[Scoped],
    desde: datetime,
    hasta: datetime,
    tz: ZoneInfo,
    buffer: timedelta,
    now: datetime,
    cap: int = DEFAULT_CAP,
) -> list[PublicSlot]:
    """Huecos libres de `[desde, hasta)` desde `now`, unidos entre sillones y sin repetidos."""
    horizonte = hasta - desde
    por_inicio: dict[datetime, PublicSlot] = {}
    for chair in chairs:
        bloqueos = [(b.starts_at, b.ends_at) for b in blocks if _applies(b, chair.chair_id)]
        ocupados = [(b.starts_at, b.ends_at) for b in busy if _applies(b, chair.chair_id)]
        for minutos, reglas in _by_duration(chair.rules).items():
            for slot in suggest_slots(
                reglas,
                blocks=bloqueos,
                busy=ocupados,
                desde=desde,
                tz=tz,
                duration=timedelta(minutes=minutos),
                buffer=buffer,
                now=now,
                n=cap,
                horizon=horizonte,
            ):
                por_inicio.setdefault(slot.starts_at, PublicSlot(slot.starts_at, slot.ends_at))
    return [por_inicio[inicio] for inicio in sorted(por_inicio)][:cap]


def chairs_on_grid(
    chairs: Sequence[ChairRules], starts_at: datetime, tz: ZoneInfo, now: datetime
) -> list[uuid.UUID]:
    """Sillones (por id) cuya grilla vigente genera exactamente `starts_at`.

    Solo mira la plantilla (no bloqueos ni ocupados): la reserva decide la disponibilidad
    real bajo lock, sillón por sillón.
    """
    candidatos: list[uuid.UUID] = []
    for chair in chairs:
        for minutos, reglas in _by_duration(chair.rules).items():
            exactos = suggest_slots(
                reglas,
                blocks=[],
                busy=[],
                desde=starts_at,
                tz=tz,
                duration=timedelta(minutes=minutos),
                buffer=timedelta(0),
                now=min(now, starts_at),
                n=1,
                horizon=_ONE_SECOND,
            )
            if any(slot.starts_at == starts_at for slot in exactos):
                candidatos.append(chair.chair_id)
                break
    return sorted(candidatos)
