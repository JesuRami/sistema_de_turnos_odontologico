"""Bordes Pydantic de turnos (C-05).

`extra="forbid"` en toda entrada (regla 2): `clinic_id`, `status`, `origin` u
`occupied_until` en el body son `422`; el tenant sale del principal y el estado
solo cambia por transiciones. Los datetimes exigen zona (`AwareDatetime`):
nunca se asume UTC (RN-GL-03).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, ClassVar, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models import (
    ActorType,
    AppointmentEventType,
    AppointmentOrigin,
    AppointmentStatus,
    CancellationReason,
)

Text500 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Notes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
DurationMin = Annotated[int, Field(ge=5, le=480)]

TransitionTarget = Literal["confirmed", "present", "absent", "no_show", "cancelled"]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _overbooking_coherente(is_overbooking: bool | None, reason: str | None) -> None:
    if is_overbooking and reason is None:
        raise ValueError("un sobreturno exige overbooking_reason (RN-SB-01)")
    if reason is not None and is_overbooking is not True:
        raise ValueError("overbooking_reason solo acompaña a is_overbooking=true")


class AppointmentCreate(_Input):
    """Alta desde recepción; la duración por defecto es el slot de la regla."""

    patient_id: uuid.UUID
    professional_id: uuid.UUID
    chair_id: uuid.UUID
    starts_at: AwareDatetime
    duration_min: DurationMin | None = None
    is_overbooking: bool = False
    overbooking_reason: Text500 | None = None
    notes: Notes | None = None

    @model_validator(mode="after")
    def _sobreturno(self) -> AppointmentCreate:
        _overbooking_coherente(self.is_overbooking, self.overbooking_reason)
        return self


class AppointmentUpdate(_Input):
    """Reprogramación (horario, duración, recursos, sobreturno) y/o edición de `notes`."""

    nullable: ClassVar[frozenset[str]] = frozenset({"notes", "overbooking_reason"})
    schedule_fields: ClassVar[frozenset[str]] = frozenset(
        {
            "starts_at",
            "duration_min",
            "professional_id",
            "chair_id",
            "is_overbooking",
            "overbooking_reason",
        }
    )

    starts_at: AwareDatetime | None = None
    duration_min: DurationMin | None = None
    professional_id: uuid.UUID | None = None
    chair_id: uuid.UUID | None = None
    is_overbooking: bool | None = None
    overbooking_reason: Text500 | None = None
    notes: Notes | None = None

    @model_validator(mode="after")
    def _coherencia(self) -> AppointmentUpdate:
        for campo in self.model_fields_set - self.nullable:
            if getattr(self, campo) is None:
                raise ValueError(f"{campo} no admite null")
        if "is_overbooking" in self.model_fields_set and self.is_overbooking:
            _overbooking_coherente(True, self.overbooking_reason)
        elif self.overbooking_reason is not None and self.is_overbooking is False:
            raise ValueError("overbooking_reason solo acompaña a is_overbooking=true")
        return self


class TransitionRequest(_Input):
    """Cambio de estado (D6). Cancelar exige motivo del catálogo (RN-CX-04)."""

    to: TransitionTarget
    reason: CancellationReason | None = None
    note: Notes | None = None

    @model_validator(mode="after")
    def _motivo(self) -> TransitionRequest:
        if self.to == "cancelled" and self.reason is None:
            raise ValueError("cancelar exige reason")
        if self.to != "cancelled" and (self.reason is not None or self.note is not None):
            raise ValueError("reason y note solo aplican a la cancelación")
        return self


class CancelInstruction(_Input):
    """Turno a cancelar en la misma operación que un bloqueo (RN-BL-02)."""

    appointment_id: uuid.UUID
    reason: CancellationReason
    note: Notes | None = None


# ------------------------------------------------------------------ lectura


class PatientContact(BaseModel):
    """Paciente con contacto: vista de admin y recepción."""

    id: uuid.UUID
    full_name: str
    phone_e164: str | None
    email: str | None


class PatientMinimal(BaseModel):
    """Paciente sin contacto: vista del odontólogo (D12)."""

    id: uuid.UUID
    full_name: str


class AppointmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient: PatientContact | PatientMinimal
    professional_id: uuid.UUID
    chair_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
    occupied_until: datetime
    status: AppointmentStatus
    origin: AppointmentOrigin
    is_overbooking: bool
    overbooking_reason: str | None
    cancellation_reason: CancellationReason | None
    cancellation_note: str | None
    cancelled_at: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class AppointmentPage(BaseModel):
    items: list[AppointmentRead]
    next_cursor: str | None


class AppointmentEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event: AppointmentEventType
    actor_type: ActorType
    actor_user_id: uuid.UUID | None
    from_status: AppointmentStatus | None
    to_status: AppointmentStatus | None
    payload: dict[str, Any]
    created_at: datetime


class AppointmentEventList(BaseModel):
    items: list[AppointmentEventRead]
