"""Schemas del dominio reports (C-13): reportes, auditoría de la clínica y exportación.

Solo salida (los parámetros llegan por query y se validan en el router). Ningún
campo lleva datos del paciente (regla 13).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.models import ActorType, AppointmentEventType, AppointmentStatus, ReminderChannel

CapacityBasis = Literal["current_schedule"]


class OccupancyRow(BaseModel):
    resource_id: uuid.UUID
    resource_name: str
    appointments: int
    overbookings: int
    booked_min: int
    capacity_min: int
    occupancy_pct: float


class OccupancyTotals(BaseModel):
    appointments: int
    overbookings: int
    booked_min: int
    capacity_min: int
    occupancy_pct: float


class OccupancyReport(BaseModel):
    group_by: Literal["professional", "chair"]
    from_date: date
    to_date: date
    capacity_basis: CapacityBasis = "current_schedule"
    rows: list[OccupancyRow]
    totals: OccupancyTotals


class AbsenteeismRow(BaseModel):
    professional_id: uuid.UUID
    professional_name: str
    present: int
    absent: int
    no_show: int
    late_cancellations: int
    outcomes: int
    no_show_rate: float
    absent_rate: float
    late_cancellation_rate: float


class AbsenteeismTotals(BaseModel):
    present: int
    absent: int
    no_show: int
    late_cancellations: int
    outcomes: int
    no_show_rate: float
    absent_rate: float
    late_cancellation_rate: float


class AbsenteeismReport(BaseModel):
    from_date: date
    to_date: date
    rows: list[AbsenteeismRow]
    totals: AbsenteeismTotals


class CancellationRow(BaseModel):
    reason: str
    total: int
    late: int
    in_window: int


class CancellationsReport(BaseModel):
    from_date: date
    to_date: date
    rows: list[CancellationRow]
    total: int


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    appointment_id: uuid.UUID
    event: AppointmentEventType
    actor_type: ActorType
    actor_user_id: uuid.UUID | None
    from_status: AppointmentStatus | None
    to_status: AppointmentStatus | None
    payload: dict[str, Any]
    created_at: datetime


class AuditPage(BaseModel):
    items: list[AuditEventRead]
    next_cursor: str | None


class WhatsAppReportRow(BaseModel):
    """Mensajes de un paso y canal enviados en el rango (C-10, D10); costo en USD (6 decimales)."""

    step: str
    channel: ReminderChannel
    sent: int
    delivered: int
    read: int
    failed: int
    cost_usd: str


class WhatsAppReportTotals(BaseModel):
    sent: int
    delivered: int
    read: int
    failed: int
    cost_usd: str


class WhatsAppReport(BaseModel):
    from_date: date
    to_date: date
    currency: Literal["USD"] = "USD"
    rows: list[WhatsAppReportRow]
    totals: WhatsAppReportTotals


class WaitlistReportTotals(BaseModel):
    """Totales de la conversión de la lista de espera (C-12, D9)."""

    created: int
    auto: int
    manual: int
    accepted: int
    declined: int
    expired: int
    cancelled: int
    conversion_pct: float | None


class WaitlistReportRow(WaitlistReportTotals):
    professional_id: uuid.UUID
    professional_name: str


class WaitlistReport(BaseModel):
    from_date: date
    to_date: date
    rows: list[WaitlistReportRow]
    totals: WaitlistReportTotals


# ------------------------------------------------------------------ C-14 (D8/D9)


class PilotMetric(BaseModel):
    """Una métrica de éxito del piloto con su base: `value`/`met` en `None` sin denominador."""

    key: str
    value: float | None
    target: float | None
    met: bool | None
    numerator: int
    denominator: int
    baseline_pct: float | None = None
    delta_vs_baseline_pct: float | None = None


class PilotReport(BaseModel):
    """Métricas del piloto (KB `01` §Métricas de éxito) para un rango de días locales."""

    from_date: date
    to_date: date
    overlaps: int
    overlaps_ok: bool
    no_show: PilotMetric
    confirmation_before_24h: PilotMetric
    waitlist_recovery: PilotMetric
    online_share: PilotMetric


WhatsAppBudgetStatus = Literal["disabled", "ok", "warning", "exceeded"]


class WhatsAppBudget(BaseModel):
    """Costo de WhatsApp del mes local en curso contra el umbral de la clínica (SU-07)."""

    month: str
    currency: Literal["USD"] = "USD"
    spent_usd: str
    threshold_usd: str | None
    used_pct: float | None
    status: WhatsAppBudgetStatus
