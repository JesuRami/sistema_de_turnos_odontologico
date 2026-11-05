"""Consentimiento por canal y paciente, append-only (C-09, D8; RN-WA-01).

Cada cambio agrega una fila; el estado vigente es el de la última y `patient.whatsapp_opt_in` es
su proyección, mantenida por un único escritor (`ConsentService`). La inmutabilidad la impone un
trigger. Sin PII: solo ids, canal, estado y fuente.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Index, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.appointment import pg_enum
from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.enums import ConsentSource, ConsentStatus, ReminderChannel
from app.models.notification_template import REMINDER_CHANNEL


class Consent(UUIDPrimaryKeyMixin, Base):
    """Cambio de consentimiento inmutable (sin `updated_at`, sin borrado)."""

    __tablename__ = "consent"
    __table_args__ = (
        ForeignKeyConstraint(["clinic_id"], ["clinic.id"]),
        ForeignKeyConstraint(["clinic_id", "patient_id"], ["patient.clinic_id", "patient.id"]),
        ForeignKeyConstraint(["clinic_id", "changed_by_user_id"], ["user.clinic_id", "user.id"]),
        CheckConstraint(
            "source <> 'reception' OR changed_by_user_id IS NOT NULL", name="reception_has_user"
        ),
        Index(
            "ix_consent_patient_channel_changed",
            "patient_id",
            "channel",
            text("changed_at DESC"),
        ),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    channel: Mapped[ReminderChannel] = mapped_column(REMINDER_CHANNEL, nullable=False)
    status: Mapped[ConsentStatus] = mapped_column(
        pg_enum(ConsentStatus, "consent_status"), nullable=False
    )
    source: Mapped[ConsentSource] = mapped_column(
        pg_enum(ConsentSource, "consent_source"), nullable=False
    )
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # `clock_timestamp()` (no `now()`): el "último" cambio es estable dentro de una transacción.
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()"), nullable=False
    )
