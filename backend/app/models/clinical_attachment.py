"""Adjuntos clínicos (C-15, D7): metadatos acá, bytes tras `AttachmentStorage`.

`storage_key` es opaco (`<clinic_id>/<uuid hex>`), lo genera el servidor y nunca lleva nombre de
archivo ni datos del paciente. La baja es lógica (`clinical_attachment_removal`, una por adjunto)
y el archivo no se borra. Ambas tablas son append-only.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CHAR,
    BigInteger,
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
from app.models.clinical_common import ATTACHMENT_KIND
from app.models.enums import AttachmentKind

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
ALLOWED_CONTENT_TYPES = ("image/jpeg", "image/png", "application/pdf")
DISPLAY_NAME_MAX_LENGTH = 255


class ClinicalAttachment(UUIDPrimaryKeyMixin, Base):
    """Metadatos inmutables de un archivo clínico."""

    __tablename__ = "clinical_attachment"
    __table_args__ = (
        UniqueConstraint("clinic_id", "id"),
        UniqueConstraint("storage_key"),
        ForeignKeyConstraint(["clinic_id"], ["clinic.id"], name="fk_clinical_attachment_clinic"),
        ForeignKeyConstraint(
            ["clinic_id", "record_id"],
            ["clinical_record.clinic_id", "clinical_record.id"],
            name="fk_clinical_attachment_record",
        ),
        ForeignKeyConstraint(
            ["clinic_id", "evolution_id"],
            ["clinical_evolution.clinic_id", "clinical_evolution.id"],
            name="fk_clinical_attachment_evolution",
        ),
        ForeignKeyConstraint(
            ["clinic_id", "created_by_user_id"],
            ["user.clinic_id", "user.id"],
            name="fk_clinical_attachment_creator",
        ),
        CheckConstraint(
            f"size_bytes BETWEEN 1 AND {MAX_ATTACHMENT_BYTES}", name="size_bytes_range"
        ),
        CheckConstraint(
            "content_type IN ('image/jpeg', 'image/png', 'application/pdf')",
            name="content_type_allowed",
        ),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
        CheckConstraint(
            f"char_length(display_name) BETWEEN 1 AND {DISPLAY_NAME_MAX_LENGTH}",
            name="display_name_length",
        ),
        Index(
            "ix_clinical_attachment_record_created",
            "record_id",
            text("created_at DESC"),
            text("id DESC"),
        ),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    evolution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    kind: Mapped[AttachmentKind] = mapped_column(ATTACHMENT_KIND, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()"), nullable=False
    )


class ClinicalAttachmentRemoval(UUIDPrimaryKeyMixin, Base):
    """Baja lógica (una por adjunto) con motivo; el archivo se conserva."""

    __tablename__ = "clinical_attachment_removal"
    __table_args__ = (
        UniqueConstraint("attachment_id"),
        ForeignKeyConstraint(
            ["clinic_id"], ["clinic.id"], name="fk_clinical_attachment_removal_clinic"
        ),
        ForeignKeyConstraint(
            ["clinic_id", "attachment_id"],
            ["clinical_attachment.clinic_id", "clinical_attachment.id"],
            name="fk_clinical_attachment_removal_attachment",
        ),
        ForeignKeyConstraint(
            ["clinic_id", "removed_by_user_id"],
            ["user.clinic_id", "user.id"],
            name="fk_clinical_attachment_removal_actor",
        ),
        CheckConstraint("char_length(reason) BETWEEN 10 AND 300", name="reason_length"),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    attachment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    removed_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
