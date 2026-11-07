"""Schemas del dominio reminders (C-01 stub; timeline, reenvío y seguimiento en C-11).

Bordes con `extra='forbid'` (regla 2). Ninguna respuesta lleva teléfono, email, DNI, links de
gestión ni ids del proveedor (regla 13); el seguimiento expone solo el nombre del paciente, y
solo a admin/recepción de su clínica.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.models import AppointmentStatus, ReminderChannel

DetailValue = str | int | bool | None


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RemindersStub(_Strict):
    """Placeholder con validación estricta de borde."""

    ping: str = "ok"


class TimelineEventRead(_Strict):
    type: str
    occurred_at: datetime
    # Evento de un intento anterior a un reenvío manual ("envío anterior").
    previous: bool
    detail: dict[str, DetailValue]


class TimelineStepRead(_Strict):
    step: str
    channel: ReminderChannel
    status: str
    reason: str | None
    scheduled_for: datetime
    available_at: datetime
    sent_at: datetime | None
    attempts: int
    last_error: str | None
    manual_resends_today: int
    last_manual_resend_at: datetime | None
    can_resend: bool
    resend_blocked_reason: str | None
    events: list[TimelineEventRead]


class TimelineRead(_Strict):
    appointment_id: uuid.UUID
    timezone: str
    pending_confirmation: bool
    steps: list[TimelineStepRead]


class ResendRequest(_Strict):
    note: str | None = None


class ResendAccepted(_Strict):
    job_id: uuid.UUID
    status: Literal["scheduled"]
    available_at: datetime
    manual_resends_today: int
    cooldown_until: datetime


FollowUpReason = Literal["no_response", "delivery_failed"]


class LastReminderRead(_Strict):
    step: str
    channel: ReminderChannel
    status: str
    sent_at: datetime | None
    last_error: str | None


class FollowUpRow(_Strict):
    appointment_id: uuid.UUID
    starts_at: datetime
    patient_id: uuid.UUID
    patient_name: str
    professional_id: uuid.UUID
    status: AppointmentStatus
    reasons: list[FollowUpReason]
    last_reminder: LastReminderRead | None
    can_confirm: bool


class FollowUpTotals(_Strict):
    no_response: int
    delivery_failed: int


class FollowUpPage(_Strict):
    items: list[FollowUpRow]
    totals: FollowUpTotals
    next_cursor: str | None
