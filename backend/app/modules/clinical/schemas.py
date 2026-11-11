"""Schemas del borde clínico (C-15). Regla 2: toda entrada con `extra='forbid'`.

Ningún schema de entrada acepta `professional_id`, `signed_at`, `created_by_user_id` ni totales:
la autoría, el reloj y los importes calculados salen del servidor (D4, D6, D8).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

from app.models import AttachmentKind, ClinicalAction, EvolutionKind
from app.models.clinical_evolution import BODY_MAX_LENGTH, REASON_MAX_LENGTH, REASON_MIN_LENGTH
from app.models.odontogram_event import NOTE_MAX_LENGTH
from app.modules.clinical.catalog import SYSTEMIC_CONDITION_CODES
from app.modules.clinical.fdi import is_valid_tooth


class StrictInput(BaseModel):
    """Base de toda entrada clínica: campos desconocidos → `422`."""

    model_config = ConfigDict(extra="forbid")


ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]

# ------------------------------------------------------------------ ficha


class RecordOpened(BaseModel):
    record_id: uuid.UUID
    patient_id: uuid.UUID
    created_at: datetime
    created: bool


# ------------------------------------------------------------------ anamnesis (Decisión 9)

OBSERVATIONS_MAX_LENGTH = 1000


class AnamnesisAnswers(StrictInput):
    """Campos estructurados fijos (provisionales hasta validar con la clínica piloto)."""

    allergies: list[ShortText] = Field(default_factory=list, max_length=20)
    medications: list[ShortText] = Field(default_factory=list, max_length=20)
    systemic_conditions: list[str] = Field(default_factory=list, max_length=20)
    pregnant: bool | None = None
    smoker: bool = False
    anticoagulants: bool = False
    observations: str = Field(default="", max_length=OBSERVATIONS_MAX_LENGTH)

    @field_validator("systemic_conditions")
    @classmethod
    def _codigos_del_catalogo(cls, valores: list[str]) -> list[str]:
        if any(v not in SYSTEMIC_CONDITION_CODES for v in valores):
            raise ValueError("condición sistémica desconocida")
        if len(set(valores)) != len(valores):
            raise ValueError("condición sistémica repetida")
        return sorted(valores)


class AnamnesisCreate(StrictInput):
    expected_version: int = Field(ge=0)
    answers: AnamnesisAnswers


class AnamnesisRead(BaseModel):
    id: uuid.UUID
    version: int
    answers: dict[str, Any]
    created_by_user_id: uuid.UUID
    created_at: datetime


class AnamnesisVersionsPage(BaseModel):
    items: list[AnamnesisRead]
    next_cursor: int | None


class RecordRead(BaseModel):
    record_id: uuid.UUID
    patient_id: uuid.UUID
    patient_name: str
    patient_archived: bool
    created_at: datetime
    anamnesis: AnamnesisRead | None
    evolutions_count: int
    attachments_count: int
    plans_count: int


# ------------------------------------------------------------------ bitácora


class AccessEventRead(BaseModel):
    id: uuid.UUID
    actor_user_id: uuid.UUID
    action: ClinicalAction
    object_type: str | None
    object_id: uuid.UUID | None
    payload: dict[str, Any]
    created_at: datetime


class AccessLogPage(BaseModel):
    items: list[AccessEventRead]
    next_cursor: str | None


# ------------------------------------------------------------------ odontograma

Surface = Literal["M", "D", "O", "V", "L", "W"]
DentitionName = Literal["permanent", "deciduous"]


def _fdi(tooth: int) -> int:
    if not is_valid_tooth(tooth):
        raise ValueError("pieza FDI inválida")
    return tooth


Tooth = Annotated[int, Field(strict=True), AfterValidator(_fdi)]


class OdontogramEntry(StrictInput):
    tooth: Tooth
    surface: Surface
    condition_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=NOTE_MAX_LENGTH)
    evolution_id: uuid.UUID | None = None


class OdontogramBatch(StrictInput):
    entries: list[OdontogramEntry] = Field(min_length=1, max_length=32)


class ConditionRead(BaseModel):
    id: uuid.UUID
    code: str
    label: str
    category: str
    scope: str
    active: bool


class ConditionsList(BaseModel):
    items: list[ConditionRead]


class OdontogramEventRead(BaseModel):
    id: uuid.UUID
    tooth: int
    surface: Surface
    dentition: DentitionName
    condition_id: uuid.UUID | None
    condition_code: str | None
    condition_label: str | None
    note: str | None
    evolution_id: uuid.UUID | None
    professional_id: uuid.UUID
    created_by_user_id: uuid.UUID
    created_at: datetime


class OdontogramEventsCreated(BaseModel):
    items: list[OdontogramEventRead]


class SurfaceState(BaseModel):
    surface: Surface
    condition_id: uuid.UUID | None
    condition_code: str | None
    condition_label: str | None
    event_id: uuid.UUID | None
    recorded_at: datetime | None


class ToothState(BaseModel):
    tooth: int
    surfaces: list[SurfaceState]


class OdontogramRead(BaseModel):
    dentition: DentitionName
    teeth: list[ToothState]


class ToothHistoryPage(BaseModel):
    items: list[OdontogramEventRead]
    next_cursor: str | None


# ------------------------------------------------------------------ evoluciones

EvolutionBody = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=BODY_MAX_LENGTH)
]
Reason = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=REASON_MIN_LENGTH, max_length=REASON_MAX_LENGTH
    ),
]


class EvolutionCreate(StrictInput):
    body: EvolutionBody
    appointment_id: uuid.UUID | None = None


class CorrectionCreate(StrictInput):
    reason: Reason
    body: EvolutionBody


class EvolutionRead(BaseModel):
    id: uuid.UUID
    record_id: uuid.UUID
    kind: EvolutionKind
    body: str
    appointment_id: uuid.UUID | None
    professional_id: uuid.UUID
    created_by_user_id: uuid.UUID
    signed_at: datetime
    content_sha256: str
    corrects_evolution_id: uuid.UUID | None
    reason: str | None
    corrected_by: uuid.UUID | None = None


class EvolutionsPage(BaseModel):
    items: list[EvolutionRead]
    next_cursor: str | None


# ------------------------------------------------------------------ adjuntos


class RemovalCreate(StrictInput):
    reason: Reason


class AttachmentRead(BaseModel):
    id: uuid.UUID
    kind: AttachmentKind
    content_type: str
    size_bytes: int
    sha256: str
    display_name: str
    evolution_id: uuid.UUID | None
    created_by_user_id: uuid.UUID
    created_at: datetime
    removed: bool = False
    removal_reason: str | None = None
    removed_at: datetime | None = None


class AttachmentsPage(BaseModel):
    items: list[AttachmentRead]
    next_cursor: str | None


class RemovalRead(BaseModel):
    attachment_id: uuid.UUID
    reason: str
    removed_by_user_id: uuid.UUID
    removed_at: datetime


# ------------------------------------------------------------------ presupuestos (D8)

BIGINT_MAX = 2**63 - 1
INT_MAX = 2**31 - 1


class PlanItemIn(StrictInput):
    phase: Annotated[int, Field(strict=True, ge=1, le=10)]
    description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)
    ]
    quantity: Annotated[int, Field(strict=True, ge=1, le=INT_MAX)]
    unit_price_cents: Annotated[int, Field(strict=True, ge=0, le=BIGINT_MAX)]
    tooth: Tooth | None = None
    surface: Surface | None = None

    @field_validator("surface")
    @classmethod
    def _cara_con_pieza(cls, valor: str | None, info: Any) -> str | None:
        if valor is not None and info.data.get("tooth") is None:
            raise ValueError("la cara requiere pieza")
        return valor


PlanItems = Annotated[list[PlanItemIn], Field(min_length=1, max_length=50)]


class PlanCreate(StrictInput):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=120)]
    items: PlanItems


class PlanVersionCreate(StrictInput):
    expected_version: int = Field(ge=1)
    items: PlanItems


class DecisionCreate(StrictInput):
    decision: Literal["accepted", "rejected"]
    note: str | None = Field(default=None, max_length=300)


class PlanItemRead(BaseModel):
    position: int
    phase: int
    description: str
    quantity: int
    unit_price_cents: int
    subtotal_cents: int
    tooth: int | None
    surface: str | None


class PhaseRead(BaseModel):
    phase: int
    subtotal_cents: int
    items: list[PlanItemRead]


class DecisionRead(BaseModel):
    decision: str
    note: str | None
    decided_by_user_id: uuid.UUID
    created_at: datetime


class PlanVersionRead(BaseModel):
    version: int
    created_at: datetime
    created_by_user_id: uuid.UUID
    phases: list[PhaseRead]
    total_cents: int
    decision: DecisionRead | None


class PlanDetail(BaseModel):
    id: uuid.UUID
    record_id: uuid.UUID
    title: str
    created_at: datetime
    latest_version: int
    versions: list[PlanVersionRead]


class PlanSummary(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    latest_version: int
    total_cents: int
    decision: str | None


class PlansPage(BaseModel):
    items: list[PlanSummary]
    next_cursor: str | None
