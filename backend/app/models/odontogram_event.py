"""Hallazgos del odontograma como eventos append-only (C-15, D3).

El estado vigente de cada (pieza, cara) es la última entrada por `(created_at, id)`; nunca se
guarda una fila mutable (regla 8). `condition_id` nulo = "limpiar". `created_at` usa
`clock_timestamp()` para ordenar también las entradas de una misma transacción.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.clinical_common import TOOTH_SURFACE, fdi_tooth_sql
from app.models.enums import ToothSurface

NOTE_MAX_LENGTH = 500


class OdontogramEvent(UUIDPrimaryKeyMixin, Base):
    """Una entrada inmutable sobre una pieza y cara."""

    __tablename__ = "odontogram_event"
    __table_args__ = (
        UniqueConstraint("clinic_id", "id"),
        ForeignKeyConstraint(["clinic_id"], ["clinic.id"], name="fk_odontogram_event_clinic"),
        ForeignKeyConstraint(
            ["clinic_id", "record_id"],
            ["clinical_record.clinic_id", "clinical_record.id"],
            name="fk_odontogram_event_record",
        ),
        ForeignKeyConstraint(
            ["clinic_id", "condition_id"],
            ["odontogram_condition.clinic_id", "odontogram_condition.id"],
            name="fk_odontogram_event_condition",
        ),
        ForeignKeyConstraint(
            ["clinic_id", "evolution_id"],
            ["clinical_evolution.clinic_id", "clinical_evolution.id"],
            name="fk_odontogram_event_evolution",
        ),
        ForeignKeyConstraint(
            ["clinic_id", "professional_id"],
            ["professional.clinic_id", "professional.id"],
            name="fk_odontogram_event_professional",
        ),
        ForeignKeyConstraint(
            ["clinic_id", "created_by_user_id"],
            ["user.clinic_id", "user.id"],
            name="fk_odontogram_event_creator",
        ),
        CheckConstraint(fdi_tooth_sql("tooth"), name="fdi_tooth"),
        CheckConstraint(
            f"note IS NULL OR char_length(note) <= {NOTE_MAX_LENGTH}", name="note_length"
        ),
        # Proyección `DISTINCT ON (tooth, surface)` e historial por pieza (D2/D3).
        Index(
            "ix_odontogram_event_projection",
            "record_id",
            "tooth",
            "surface",
            text("created_at DESC"),
            text("id DESC"),
        ),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tooth: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    surface: Mapped[ToothSurface] = mapped_column(TOOTH_SURFACE, nullable=False)
    condition_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    evolution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    professional_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()"), nullable=False
    )
