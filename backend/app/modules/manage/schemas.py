"""Bordes Pydantic de la gestión por token (C-08, D5).

La vista expone lo mínimo para reconocer el turno: sin ids de turno, paciente, sillón ni
profesional, y sin contacto del paciente. Las fechas salen en la zona de la clínica.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, StringConstraints

from app.models import AppointmentOrigin, AppointmentStatus
from app.modules.manage.reasons import PatientReason, ReasonOption

BlockedReason = Literal["window_closed", "past", "not_manageable", "token_expired"]


class ManageClinic(BaseModel):
    name: str
    phone: str | None
    timezone: str
    slug: str


class ManageAppointment(BaseModel):
    patient_first_name: str
    starts_at: datetime
    ends_at: datetime
    professional_display_name: str
    status: AppointmentStatus
    origin: AppointmentOrigin
    is_overbooking: bool


class ManagePolicy(BaseModel):
    cancellation_window_hours: int
    cancellation_closes_at: datetime


class ManageActions(BaseModel):
    """Qué puede hacer el paciente ahora; la UI no reimplementa reglas."""

    can_confirm: bool
    can_cancel: bool
    can_reschedule: bool
    blocked_reason: BlockedReason | None


class ManageView(BaseModel):
    clinic: ManageClinic
    appointment: ManageAppointment
    policy: ManagePolicy
    actions: ManageActions
    reason_options: list[ReasonOption]
    manage_token_expires_at: datetime


class ManageSlot(BaseModel):
    """Hueco ofrecible para reprogramar: solo inicio y fin (sin sillón ni profesional)."""

    starts_at: datetime
    ends_at: datetime


class ManageAvailability(BaseModel):
    timezone: str
    slots: list[ManageSlot]


NOTE_MAX = 200
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=NOTE_MAX)]


class _Action(BaseModel):
    """Una acción por request, sin campos extra (regla 2)."""

    model_config = ConfigDict(extra="forbid")


class ConfirmRequest(_Action):
    action: Literal["confirm"]


class CancelRequest(_Action):
    """Motivo opcional de la lista cerrada; la nota libre solo se guarda con `otro` (D7)."""

    action: Literal["cancel"]
    reason: PatientReason | None = None
    note: Note | None = None


class RescheduleRequest(_Action):
    """El paciente elige solo el inicio: profesional y duración no cambian (D8)."""

    action: Literal["reschedule"]
    starts_at: AwareDatetime


# El discriminador se declara en el `Body()` del router: anidado en otro `Annotated`, FastAPI
# lo pierde y valida contra las tres variantes (errores de todas en el 422).
ManageAction = ConfirmRequest | CancelRequest | RescheduleRequest
