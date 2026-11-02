"""Plantilla semanal de disponibilidad profesional+sillón (C-02: solo estructura).

El anti-solape de reglas (RN-AG-05) y los bloqueos llegan en C-04.
"""

import uuid
from datetime import date, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    Time,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class ScheduleRule(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """Franja semanal; las referencias son compuestas `(clinic_id, *_id)` (intra-tenant)."""

    __tablename__ = "schedule_rule"
    __table_args__ = (
        ForeignKeyConstraint(
            ["clinic_id", "professional_id"], ["professional.clinic_id", "professional.id"]
        ),
        ForeignKeyConstraint(["clinic_id", "chair_id"], ["chair.clinic_id", "chair.id"]),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint("start_time < end_time", name="time_order"),
        CheckConstraint("slot_duration_min > 0", name="slot_positive"),
        CheckConstraint("valid_to IS NULL OR valid_from <= valid_to", name="validity_order"),
        Index(None, "professional_id", "chair_id", "weekday"),
    )

    professional_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    chair_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    slot_duration_min: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_from: Mapped[date] = mapped_column(
        Date, nullable=False, server_default=func.current_date()
    )
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
