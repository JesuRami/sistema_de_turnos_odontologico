"""Métricas de éxito del piloto (C-14, D9; KB `01` §Métricas de éxito).

Todas sobre eventos append-only (regla 8) salvo la **integridad de agenda**, que por definición
audita la tabla de turnos (KB `01`: "auditoría de integridad sobre tabla de turnos") y debe dar 0
siempre: la invariante la impone el EXCLUDE de C-05; esta consulta es la evidencia del piloto.

- `overlaps` (meta 0): turnos vigentes no sobreturno que se pisan por profesional o sillón.
- `no_show_rate` (meta −20 % vs. línea base): reporte de ausentismo de C-13, sobre eventos.
- `confirmation_before_24h_rate` (meta ≥ 60 %): turnos nacidos `pending` con ≥ 24 h de
  anticipación y confirmados antes de T−24 h (`appointment_event`).
- `waitlist_recovery_rate` (meta ≥ 10 %): ofertas `offer_accepted` (`waitlist_event`) sobre
  cancelaciones del rango (`appointment_event`).
- `online_share` (meta ≥ 30 %): altas con `payload.origin = 'online'` sobre todas las altas.

Las consultas son SQL explícito (columnas nombradas, sin `SELECT *`), parametrizado y acotado a la
clínica del principal (regla 4). Sin datos personales en la salida.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.reports.schemas import PilotMetric, PilotReport
from app.modules.reports.service import ReportsService, ReportWindow

VIGENT_SQL = "('pending', 'confirmed', 'present')"

_OVERLAPS = f"""
SELECT count(*) AS overlaps
FROM appointment a
JOIN appointment b
  ON b.clinic_id = a.clinic_id
 AND b.id > a.id
 AND (b.professional_id = a.professional_id OR b.chair_id = a.chair_id)
 AND tstzrange(b.starts_at, b.occupied_until) && tstzrange(a.starts_at, a.occupied_until)
WHERE a.clinic_id = :clinic_id
  AND a.status IN {VIGENT_SQL} AND b.status IN {VIGENT_SQL}
  AND NOT a.is_overbooking AND NOT b.is_overbooking
  AND a.starts_at < :end_at AND a.occupied_until > :start_at
"""
OVERLAPS_SQL = text(_OVERLAPS)

_CONFIRMATION = """
WITH nacidos AS (
  SELECT e.appointment_id, e.created_at AS creado
  FROM appointment_event e
  WHERE e.clinic_id = :clinic_id
    AND e.event = 'created'
    AND e.to_status = 'pending'
),
ultimo AS (
  SELECT DISTINCT ON (e.appointment_id) e.appointment_id, e.slot_starts_at
  FROM appointment_event e
  WHERE e.clinic_id = :clinic_id
    AND e.slot_starts_at IS NOT NULL
    AND e.appointment_id IN (SELECT n.appointment_id FROM nacidos n)
  ORDER BY e.appointment_id, e.created_at DESC, e.id DESC
),
base AS (
  SELECT n.appointment_id, u.slot_starts_at
  FROM nacidos n
  JOIN ultimo u ON u.appointment_id = n.appointment_id
  WHERE u.slot_starts_at >= :start_at
    AND u.slot_starts_at < :end_at
    AND n.creado <= u.slot_starts_at - interval '24 hours'
)
SELECT
  count(*) AS base,
  count(*) FILTER (
    WHERE EXISTS (
      SELECT 1 FROM appointment_event c
      WHERE c.clinic_id = :clinic_id
        AND c.appointment_id = b.appointment_id
        AND c.event = 'confirmed'
        AND c.created_at <= b.slot_starts_at - interval '24 hours'
    )
  ) AS confirmed
FROM base b
"""
CONFIRMATION_SQL = text(_CONFIRMATION)

_RECOVERY = """
SELECT
  (
    SELECT count(*)
    FROM waitlist_event w
    JOIN waitlist_offer o ON o.id = w.offer_id AND o.clinic_id = w.clinic_id
    WHERE w.clinic_id = :clinic_id
      AND w.event = 'offer_accepted'
      AND o.starts_at >= :start_at AND o.starts_at < :end_at
  ) AS accepted,
  (
    SELECT count(DISTINCT e.appointment_id)
    FROM appointment_event e
    WHERE e.clinic_id = :clinic_id
      AND e.event = 'cancelled'
      AND e.slot_starts_at >= :start_at AND e.slot_starts_at < :end_at
  ) AS cancellations
"""
RECOVERY_SQL = text(_RECOVERY)

_ONLINE = """
SELECT
  count(*) AS total,
  count(*) FILTER (WHERE e.payload ->> 'origin' = 'online') AS online
FROM appointment_event e
WHERE e.clinic_id = :clinic_id
  AND e.event IN ('created', 'overbooking_created')
  AND e.slot_starts_at >= :start_at AND e.slot_starts_at < :end_at
"""
ONLINE_SQL = text(_ONLINE)

TARGET_CONFIRMATION = 0.60
TARGET_RECOVERY = 0.10
TARGET_ONLINE = 0.30
TARGET_NO_SHOW_REDUCTION_PCT = -20.0


@dataclass(frozen=True, slots=True)
class Ratio:
    numerator: int
    denominator: int

    @property
    def value(self) -> float | None:
        return round(self.numerator / self.denominator, 4) if self.denominator else None


def _metric(key: str, ratio: Ratio, target: float, *, higher_is_better: bool = True) -> PilotMetric:
    valor = ratio.value
    cumple = None if valor is None else (valor >= target if higher_is_better else valor <= target)
    return PilotMetric(
        key=key,
        value=valor,
        target=target,
        met=cumple,
        numerator=ratio.numerator,
        denominator=ratio.denominator,
    )


def _params(clinic_id: uuid.UUID, w: ReportWindow) -> dict[str, object]:
    return {"clinic_id": clinic_id, "start_at": w.start_at, "end_at": w.end_at}


async def pilot_report(
    session: AsyncSession,
    clinic_id: uuid.UUID,
    desde: date,
    hasta: date,
    *,
    baseline_no_show_pct: float | None = None,
) -> PilotReport:
    servicio = ReportsService(session, clinic_id)
    w = await servicio.window(desde, hasta)
    params = _params(clinic_id, w)

    overlaps = int((await session.execute(OVERLAPS_SQL, params)).scalar_one())
    conf = (await session.execute(CONFIRMATION_SQL, params)).one()
    rec = (await session.execute(RECOVERY_SQL, params)).one()
    onl = (await session.execute(ONLINE_SQL, params)).one()
    ausentismo = (await servicio.absenteeism(desde, hasta)).totals

    no_show = Ratio(ausentismo.no_show, ausentismo.outcomes)
    delta: float | None = None
    met_no_show: bool | None = None
    if baseline_no_show_pct is not None and baseline_no_show_pct > 0 and no_show.value is not None:
        actual_pct = no_show.value * 100
        delta = round((actual_pct - baseline_no_show_pct) / baseline_no_show_pct * 100, 2)
        met_no_show = delta <= TARGET_NO_SHOW_REDUCTION_PCT

    return PilotReport(
        from_date=desde,
        to_date=hasta,
        overlaps=overlaps,
        overlaps_ok=overlaps == 0,
        no_show=PilotMetric(
            key="no_show_rate",
            value=no_show.value,
            target=None,
            met=met_no_show,
            numerator=no_show.numerator,
            denominator=no_show.denominator,
            baseline_pct=baseline_no_show_pct,
            delta_vs_baseline_pct=delta,
        ),
        confirmation_before_24h=_metric(
            "confirmation_before_24h_rate",
            Ratio(int(conf.confirmed), int(conf.base)),
            TARGET_CONFIRMATION,
        ),
        waitlist_recovery=_metric(
            "waitlist_recovery_rate",
            Ratio(int(rec.accepted), int(rec.cancellations)),
            TARGET_RECOVERY,
        ),
        online_share=_metric("online_share", Ratio(int(onl.online), int(onl.total)), TARGET_ONLINE),
    )
