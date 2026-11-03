"""Auditoría append-only de fusiones de pacientes (C-06, D9).

Igual que las demás auditorías, la inmutabilidad la impone un trigger `BEFORE
UPDATE OR DELETE`. Guarda solo ids y nombres de campos completados: nunca
nombre, teléfono ni email (regla 13).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Index, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class PatientMerge(UUIDPrimaryKeyMixin, Base):
    """Registro inmutable de una fusión `source` → `target`."""

    __tablename__ = "patient_merge"
    __table_args__ = (
        ForeignKeyConstraint(["clinic_id"], ["clinic.id"]),
        ForeignKeyConstraint(
            ["source_patient_id", "clinic_id"], ["patient.id", "patient.clinic_id"]
        ),
        ForeignKeyConstraint(
            ["target_patient_id", "clinic_id"], ["patient.id", "patient.clinic_id"]
        ),
        ForeignKeyConstraint(["clinic_id", "actor_user_id"], ["user.clinic_id", "user.id"]),
        CheckConstraint("source_patient_id <> target_patient_id", name="distinct_patients"),
        CheckConstraint(
            "jsonb_typeof(appointment_ids) = 'array' AND jsonb_typeof(filled_fields) = 'array'",
            name="payload_are_arrays",
        ),
        Index(None, "clinic_id", "created_at"),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    target_patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    appointment_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    filled_fields: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    # `clock_timestamp()`: orden estable también dentro de una transacción.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()"), nullable=False
    )
