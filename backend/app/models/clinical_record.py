"""Ficha clínica por paciente (C-15, D2): fila de anclaje inmutable, 1:1 con `patient`.

Engancha por `(clinic_id, patient_id)` sin tocar `patient` (DD-02). Append-only: trigger
`BEFORE UPDATE OR DELETE` y sin `UPDATE` para `app_writer`.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKeyConstraint, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class ClinicalRecord(UUIDPrimaryKeyMixin, Base):
    """Una ficha por (clínica, paciente)."""

    __tablename__ = "clinical_record"
    __table_args__ = (
        UniqueConstraint("clinic_id", "id"),
        UniqueConstraint("clinic_id", "patient_id"),
        ForeignKeyConstraint(["clinic_id"], ["clinic.id"], name="fk_clinical_record_clinic"),
        ForeignKeyConstraint(
            ["clinic_id", "patient_id"],
            ["patient.clinic_id", "patient.id"],
            name="fk_clinical_record_patient",
        ),
        ForeignKeyConstraint(
            ["clinic_id", "created_by_user_id"],
            ["user.clinic_id", "user.id"],
            name="fk_clinical_record_creator",
        ),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
