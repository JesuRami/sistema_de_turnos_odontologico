"""Bordes Pydantic de configuración de agenda (C-04).

`extra="forbid"` en toda entrada (regla 2): un `clinic_id` en el body es `422`;
el tenant sale siempre del principal. Los `PATCH` distinguen ausencia de `null`
con `model_fields_set`; `null` solo se acepta en los campos que lo permiten.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from typing import Annotated, ClassVar

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models import BlockReason
from app.modules.appointments.schemas import CancelInstruction

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Color = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]
Notes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
DurationMin = Annotated[int, Field(gt=0, le=480)]
BufferMin = Annotated[int, Field(ge=0, le=120)]
Weekday = Annotated[int, Field(ge=0, le=6)]


class _Input(BaseModel):
    """Entrada estricta de borde."""

    model_config = ConfigDict(extra="forbid")


class _Patch(_Input):
    """`PATCH` parcial: `null` explícito solo en los campos de `nullable`."""

    nullable: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def _sin_nulls_indebidos(self) -> _Patch:
        for campo in self.model_fields_set - self.nullable:
            if getattr(self, campo) is None:
                raise ValueError(f"{campo} no admite null")
        return self


# ------------------------------------------------------------ profesionales


class ProfessionalCreate(_Input):
    display_name: Name
    color: Color | None = None
    default_duration_min: DurationMin = 30
    buffer_min: BufferMin = 0
    booking_enabled: bool = True


class ProfessionalUpdate(_Patch):
    nullable: ClassVar[frozenset[str]] = frozenset({"color"})

    display_name: Name | None = None
    color: Color | None = None
    default_duration_min: DurationMin | None = None
    buffer_min: BufferMin | None = None
    booking_enabled: bool | None = None
    active: bool | None = None


class ProfessionalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_name: str
    color: str | None
    default_duration_min: int
    buffer_min: int
    booking_enabled: bool
    active: bool
    created_at: datetime


class ProfessionalPage(BaseModel):
    items: list[ProfessionalRead]
    next_cursor: str | None


# ------------------------------------------------------------------ sillones


class ChairCreate(_Input):
    name: Name


class ChairUpdate(_Patch):
    name: Name | None = None
    active: bool | None = None


class ChairRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    active: bool
    created_at: datetime


class ChairPage(BaseModel):
    items: list[ChairRead]
    next_cursor: str | None


# ------------------------------------------------------- plantilla semanal


def _minutos(inicio: time, fin: time) -> int:
    return (fin.hour * 60 + fin.minute) - (inicio.hour * 60 + inicio.minute)


class ScheduleRuleCreate(_Input):
    professional_id: uuid.UUID
    chair_id: uuid.UUID
    weekday: Weekday
    start_time: time
    end_time: time
    slot_duration_min: DurationMin
    valid_from: date
    valid_to: date | None = None

    @model_validator(mode="after")
    def _franja_y_vigencia(self) -> ScheduleRuleCreate:
        if self.start_time >= self.end_time:
            raise ValueError("start_time debe ser anterior a end_time")
        if self.slot_duration_min > _minutos(self.start_time, self.end_time):
            raise ValueError("slot_duration_min excede la franja")
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("valid_to debe ser posterior o igual a valid_from")
        return self


class ScheduleRuleUpdate(_Patch):
    """Profesional, sillón, día y `valid_from` son inmutables: se crea otra regla."""

    nullable: ClassVar[frozenset[str]] = frozenset({"valid_to"})

    start_time: time | None = None
    end_time: time | None = None
    slot_duration_min: DurationMin | None = None
    valid_to: date | None = None
    active: bool | None = None


class ScheduleRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    professional_id: uuid.UUID
    chair_id: uuid.UUID
    weekday: int
    start_time: time
    end_time: time
    slot_duration_min: int
    valid_from: date
    valid_to: date | None
    active: bool
    created_at: datetime


class ScheduleRulePage(BaseModel):
    items: list[ScheduleRuleRead]
    next_cursor: str | None


# ------------------------------------------------------------------ bloqueos


class BlockCreate(_Input):
    professional_id: uuid.UUID | None = None
    chair_id: uuid.UUID | None = None
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    reason: BlockReason
    notes: Notes | None = None
    # RN-BL-02 (C-05): turnos afectados que se cancelan en la misma transacción.
    cancel_appointments: list[CancelInstruction] = Field(default_factory=list)

    @model_validator(mode="after")
    def _objetivo_y_rango(self) -> BlockCreate:
        if self.professional_id is None and self.chair_id is None:
            raise ValueError("el bloqueo exige professional_id, chair_id o ambos (RN-BL-01)")
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at debe ser posterior a starts_at")
        return self


class BlockUpdate(_Patch):
    """Los objetivos son inmutables: cambiar a quién se bloquea es otro bloqueo."""

    nullable: ClassVar[frozenset[str]] = frozenset({"notes"})

    starts_at: AwareDatetime | None = None
    ends_at: AwareDatetime | None = None
    reason: BlockReason | None = None
    notes: Notes | None = None
    cancel_appointments: list[CancelInstruction] | None = None


class ClosureCreate(_Input):
    """Feriado o cierre de clínica (RN-BL-04): un bloqueo por sillón activo."""

    starts_at: AwareDatetime
    ends_at: AwareDatetime
    reason: BlockReason = BlockReason.FERIADO
    notes: Notes | None = None
    cancel_appointments: list[CancelInstruction] = Field(default_factory=list)

    @model_validator(mode="after")
    def _rango(self) -> ClosureCreate:
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at debe ser posterior a starts_at")
        return self


class BlockRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    professional_id: uuid.UUID | None
    chair_id: uuid.UUID | None
    starts_at: datetime
    ends_at: datetime
    reason: BlockReason
    notes: str | None
    created_by_user_id: uuid.UUID
    created_at: datetime


class BlockPage(BaseModel):
    items: list[BlockRead]
    next_cursor: str | None


class BlockList(BaseModel):
    items: list[BlockRead]
