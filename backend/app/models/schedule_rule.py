"""Plantilla semanal de disponibilidad profesional+sillón (C-02; anti-solape C-04).

RN-AG-05 / US-002 CA-2: dos reglas activas del mismo (clínica, profesional,
sillón, día) no pueden intersectar franja ni vigencia. Lo garantiza un EXCLUDE
en la base (regla dura 1), no el servicio.
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
    literal_column,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin

# Postgres no tiene `timerange`: la franja se proyecta sobre una fecha fija
# (`date + time` es inmutable). `valid_to` es inclusivo y NULL = sin fin.
SLOT_RANGE_SQL = "tsrange(DATE '2000-01-01' + start_time, DATE '2000-01-01' + end_time)"
VALIDITY_RANGE_SQL = "daterange(valid_from, valid_to, '[]')"


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
        ExcludeConstraint(
            ("clinic_id", "="),
            ("professional_id", "="),
            ("chair_id", "="),
            ("weekday", "="),
            (literal_column(SLOT_RANGE_SQL), "&&"),
            (literal_column(VALIDITY_RANGE_SQL), "&&"),
            name="ex_schedule_rule_no_overlap",
            using="gist",
            where=text("active"),
        ),
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
