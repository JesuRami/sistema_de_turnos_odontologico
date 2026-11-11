"""Anamnesis versionada (C-15): cada guardado es la versión N+1; ninguna se reescribe."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class AnamnesisVersion(UUIDPrimaryKeyMixin, Base):
    """Versión inmutable de la anamnesis de una ficha; la vigente es la mayor."""

    __tablename__ = "anamnesis_version"
    __table_args__ = (
        UniqueConstraint("clinic_id", "id"),
        UniqueConstraint("record_id", "version"),
        ForeignKeyConstraint(["clinic_id"], ["clinic.id"], name="fk_anamnesis_version_clinic"),
        ForeignKeyConstraint(
            ["clinic_id", "record_id"],
            ["clinical_record.clinic_id", "clinical_record.id"],
            name="fk_anamnesis_version_record",
        ),
        ForeignKeyConstraint(
            ["clinic_id", "created_by_user_id"],
            ["user.clinic_id", "user.id"],
            name="fk_anamnesis_version_creator",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("jsonb_typeof(answers) = 'object'", name="answers_is_object"),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    answers: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
