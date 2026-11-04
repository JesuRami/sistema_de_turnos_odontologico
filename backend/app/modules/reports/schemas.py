"""Schemas del dominio reports (C-13): reportes, auditoría de la clínica y exportación.

Solo salida (los parámetros llegan por query y se validan en el router). Ningún
campo lleva datos del paciente (regla 13).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.models import ActorType, AppointmentEventType, AppointmentStatus

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
