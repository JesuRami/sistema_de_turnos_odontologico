"""Bitácora de accesos clínicos (C-15, D5): append-only, sin contenido ni PII.

Cada lectura o escritura clínica exitosa inserta una fila en la misma transacción. El `payload`
solo admite ids, conteos y códigos cortos (CHECK `payload_safe`).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.clinical_common import ACCESS_PAYLOAD_SAFE_SQL, CLINICAL_ACTION
from app.models.enums import ClinicalAction


class ClinicalAccessEvent(UUIDPrimaryKeyMixin, Base):
    """Quién hizo qué sobre qué ficha y cuándo."""

    __tablename__ = "clinical_access_event"
    __table_args__ = (
        ForeignKeyConstraint(["clinic_id"], ["clinic.id"], name="fk_clinical_access_event_clinic"),
        ForeignKeyConstraint(
            ["clinic_id", "record_id"],
            ["clinical_record.clinic_id", "clinical_record.id"],
            name="fk_clinical_access_event_record",
        ),
        ForeignKeyConstraint(
            ["clinic_id", "actor_user_id"],
            ["user.clinic_id", "user.id"],
            name="fk_clinical_access_event_actor",
        ),
        CheckConstraint(ACCESS_PAYLOAD_SAFE_SQL, name="payload_safe"),
        CheckConstraint(
            "object_type IS NULL OR object_type ~ '^[a-z_]{1,40}$'", name="object_type_format"
        ),
        Index(
            "ix_clinical_access_event_record_created",
            "record_id",
            text("created_at DESC"),
            text("id DESC"),
        ),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[ClinicalAction] = mapped_column(CLINICAL_ACTION, nullable=False)
    object_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    object_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()"), nullable=False
    )
