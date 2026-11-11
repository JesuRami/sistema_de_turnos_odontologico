"""Evoluciones clínicas firmadas (C-15, D6): append-only, correcciones como filas nuevas.

Firma **simple** (no Ley 25.506): identidad autenticada (`professional_id` del principal) +
`signed_at` del servidor + `content_sha256` del contenido canónico.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.clinical_common import EVOLUTION_KIND
from app.models.enums import EvolutionKind

BODY_MAX_LENGTH = 4000
REASON_MIN_LENGTH = 10
REASON_MAX_LENGTH = 300


class ClinicalEvolution(UUIDPrimaryKeyMixin, Base):
    """Entrada (`entry`) o corrección (`correction`) de la historia clínica."""

    __tablename__ = "clinical_evolution"
    __table_args__ = (
        UniqueConstraint("clinic_id", "id"),
        ForeignKeyConstraint(["clinic_id"], ["clinic.id"], name="fk_clinical_evolution_clinic"),
        ForeignKeyConstraint(
            ["clinic_id", "record_id"],
            ["clinical_record.clinic_id", "clinical_record.id"],
            name="fk_clinical_evolution_record",
        ),
        ForeignKeyConstraint(
            ["clinic_id", "appointment_id"],
            ["appointment.clinic_id", "appointment.id"],
            name="fk_clinical_evolution_appointment",
        ),
        ForeignKeyConstraint(
            ["clinic_id", "professional_id"],
            ["professional.clinic_id", "professional.id"],
            name="fk_clinical_evolution_professional",
        ),
        ForeignKeyConstraint(
            ["clinic_id", "created_by_user_id"],
            ["user.clinic_id", "user.id"],
            name="fk_clinical_evolution_creator",
        ),
        ForeignKeyConstraint(
            ["clinic_id", "corrects_evolution_id"],
            ["clinical_evolution.clinic_id", "clinical_evolution.id"],
            name="fk_clinical_evolution_corrects",
        ),
        CheckConstraint(
            "(kind = 'correction') = (corrects_evolution_id IS NOT NULL) "
            "AND (kind = 'correction') = (reason IS NOT NULL)",
            name="correction_coherent",
        ),
        CheckConstraint(f"char_length(body) BETWEEN 1 AND {BODY_MAX_LENGTH}", name="body_length"),
        CheckConstraint(
            f"reason IS NULL OR char_length(reason) BETWEEN {REASON_MIN_LENGTH} "
            f"AND {REASON_MAX_LENGTH}",
            name="reason_length",
        ),
        CheckConstraint("content_sha256 ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
        CheckConstraint("corrects_evolution_id <> id", name="not_self_correction"),
        Index(
            "ix_clinical_evolution_record_signed",
            "record_id",
            text("signed_at DESC"),
            text("id DESC"),
        ),
        Index(None, "record_id", "appointment_id"),
        Index(None, "corrects_evolution_id"),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    professional_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[EvolutionKind] = mapped_column(EVOLUTION_KIND, nullable=False)
    corrects_evolution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
