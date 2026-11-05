"""Evento de entrega append-only de un `reminder_job` (C-09, D1; RN-WA-05).

Lo escribe el motor (intentos, envío, salto, cancelación, escalado) y, desde C-10, el webhook de
Meta (`delivered`/`read`). La inmutabilidad la impone un trigger `BEFORE UPDATE OR DELETE`, como
en `appointment_event`. `provider_event_id` deduplica los eventos del proveedor por job.
`payload` NO lleva nombre, teléfono, email ni link del paciente (regla 13).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.appointment import pg_enum
from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.enums import DeliveryEventType


class DeliveryEvent(UUIDPrimaryKeyMixin, Base):
    """Traza inmutable de un job (sin `updated_at`, sin borrado)."""

    __tablename__ = "delivery_event"
    __table_args__ = (
        ForeignKeyConstraint(["clinic_id"], ["clinic.id"]),
        ForeignKeyConstraint(
            ["clinic_id", "reminder_job_id"], ["reminder_job.clinic_id", "reminder_job.id"]
        ),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_is_object"),
        Index(None, "reminder_job_id", "occurred_at"),
        Index(
            "uq_delivery_event_job_provider_event",
            "reminder_job_id",
            "provider_event_id",
            unique=True,
            postgresql_where=text("provider_event_id IS NOT NULL"),
        ),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reminder_job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_type: Mapped[DeliveryEventType] = mapped_column(
        pg_enum(DeliveryEventType, "delivery_event_type"), nullable=False
    )
    provider_event_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # `clock_timestamp()` (no `now()`): ordena también los eventos de una misma transacción.
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()"), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()"), nullable=False
    )
