"""Bloqueo de agenda por profesional y/o sillón (C-04, RN-BL-01/03/04).

Al menos un objetivo es obligatorio (CHECK en la base). Las referencias son FKs
compuestas `(clinic_id, *_id)`: un bloqueo nunca apunta a recursos de otra
clínica (regla dura 4). El retiro es lógico (`removed_at`), nunca físico.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Index,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import BlockReason

NOTES_MAX_LENGTH = 500


class Block(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """Rango `[starts_at, ends_at)` cerrado para el profesional, el sillón o ambos."""

    __tablename__ = "block"
    __table_args__ = (
        ForeignKeyConstraint(
            ["clinic_id", "professional_id"], ["professional.clinic_id", "professional.id"]
        ),
        ForeignKeyConstraint(["clinic_id", "chair_id"], ["chair.clinic_id", "chair.id"]),
        ForeignKeyConstraint(["clinic_id", "created_by_user_id"], ["user.clinic_id", "user.id"]),
        ForeignKeyConstraint(["clinic_id", "removed_by_user_id"], ["user.clinic_id", "user.id"]),
        CheckConstraint("professional_id IS NOT NULL OR chair_id IS NOT NULL", name="has_target"),
        CheckConstraint("ends_at > starts_at", name="range_order"),
        CheckConstraint(f"char_length(notes) <= {NOTES_MAX_LENGTH}", name="notes_length"),
        Index(None, "clinic_id", "starts_at"),
    )

    professional_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    chair_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[BlockReason] = mapped_column(
        Enum(
            BlockReason,
            name="block_reason",
            native_enum=True,
            create_type=False,
            values_callable=lambda motivos: [m.value for m in motivos],
        ),
        nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    removed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
