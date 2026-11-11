"""Plan de tratamiento / presupuesto por fases (C-15, D8): todo inmutable.

`treatment_plan` (título) → `treatment_plan_version` (N+1 con control optimista) →
`treatment_plan_item` (centavos de ARS, `bigint`) y `treatment_plan_decision` (una por versión).
Los totales no se guardan: los calcula el servidor desde los ítems.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.clinical_common import PLAN_DECISION, TOOTH_SURFACE, fdi_tooth_sql
from app.models.enums import PlanDecision, ToothSurface

MAX_PHASES = 10


class TreatmentPlan(UUIDPrimaryKeyMixin, Base):
    """Plan de una ficha; sus versiones llevan el contenido."""

    __tablename__ = "treatment_plan"
    __table_args__ = (
        UniqueConstraint("clinic_id", "id"),
        ForeignKeyConstraint(["clinic_id"], ["clinic.id"], name="fk_treatment_plan_clinic"),
        ForeignKeyConstraint(
            ["clinic_id", "record_id"],
            ["clinical_record.clinic_id", "clinical_record.id"],
            name="fk_treatment_plan_record",
        ),
        ForeignKeyConstraint(
            ["clinic_id", "created_by_user_id"],
            ["user.clinic_id", "user.id"],
            name="fk_treatment_plan_creator",
        ),
        CheckConstraint("char_length(title) BETWEEN 3 AND 120", name="title_length"),
        Index(
            "ix_treatment_plan_record_created",
            "record_id",
            text("created_at DESC"),
            text("id DESC"),
        ),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()"), nullable=False
    )


class TreatmentPlanVersion(UUIDPrimaryKeyMixin, Base):
    """Versión inmutable N de un plan."""

    __tablename__ = "treatment_plan_version"
    __table_args__ = (
        UniqueConstraint("clinic_id", "id"),
        UniqueConstraint("plan_id", "version"),
        ForeignKeyConstraint(["clinic_id"], ["clinic.id"], name="fk_treatment_plan_version_clinic"),
        ForeignKeyConstraint(
            ["clinic_id", "plan_id"],
            ["treatment_plan.clinic_id", "treatment_plan.id"],
            name="fk_treatment_plan_version_plan",
        ),
        ForeignKeyConstraint(
            ["clinic_id", "created_by_user_id"],
            ["user.clinic_id", "user.id"],
            name="fk_treatment_plan_version_creator",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TreatmentPlanItem(UUIDPrimaryKeyMixin, Base):
    """Ítem de una versión: fase, posición, cantidad y precio unitario en centavos."""

    __tablename__ = "treatment_plan_item"
    __table_args__ = (
        UniqueConstraint("version_id", "position"),
        ForeignKeyConstraint(["clinic_id"], ["clinic.id"], name="fk_treatment_plan_item_clinic"),
        ForeignKeyConstraint(
            ["clinic_id", "version_id"],
            ["treatment_plan_version.clinic_id", "treatment_plan_version.id"],
            name="fk_treatment_plan_item_version",
        ),
        CheckConstraint(f"phase BETWEEN 1 AND {MAX_PHASES}", name="phase_range"),
        CheckConstraint("position >= 1", name="position_positive"),
        CheckConstraint("quantity >= 1", name="quantity_positive"),
        CheckConstraint("unit_price_cents >= 0", name="unit_price_nonneg"),
        CheckConstraint("char_length(description) BETWEEN 3 AND 200", name="description_length"),
        CheckConstraint(f"tooth IS NULL OR ({fdi_tooth_sql('tooth')})", name="fdi_tooth"),
        CheckConstraint("surface IS NULL OR tooth IS NOT NULL", name="surface_needs_tooth"),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    phase: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tooth: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    surface: Mapped[ToothSurface | None] = mapped_column(TOOTH_SURFACE, nullable=True)


class TreatmentPlanDecision(UUIDPrimaryKeyMixin, Base):
    """Aceptación o rechazo de una versión (a lo sumo una por versión)."""

    __tablename__ = "treatment_plan_decision"
    __table_args__ = (
        UniqueConstraint("version_id"),
        ForeignKeyConstraint(
            ["clinic_id"], ["clinic.id"], name="fk_treatment_plan_decision_clinic"
        ),
        ForeignKeyConstraint(
            ["clinic_id", "version_id"],
            ["treatment_plan_version.clinic_id", "treatment_plan_version.id"],
            name="fk_treatment_plan_decision_version",
        ),
        ForeignKeyConstraint(
            ["clinic_id", "decided_by_user_id"],
            ["user.clinic_id", "user.id"],
            name="fk_treatment_plan_decision_actor",
        ),
        CheckConstraint("note IS NULL OR char_length(note) <= 300", name="note_length"),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    decision: Mapped[PlanDecision] = mapped_column(PLAN_DECISION, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
