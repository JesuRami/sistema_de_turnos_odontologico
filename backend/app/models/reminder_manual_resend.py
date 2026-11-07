"""Auditoría append-only de los reenvíos manuales de un recordatorio (C-11, D1; US-032 CA-2).

Cada fila es una acción de recepción sobre un `reminder_job`: quién la hizo, cuándo y una nota
operativa opcional. `reminder_job.manual_resend_at` guarda solo el último reenvío; esta tabla
conserva todos. La inmutabilidad la impone un trigger `BEFORE UPDATE OR DELETE` (regla 7) y las
FKs compuestas impiden referenciar un turno, job o usuario de otra clínica (regla 4).

`note` es corta (≤ 200) y el endpoint rechaza teléfonos, emails y DNI (regla 13).
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Index, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, UUIDPrimaryKeyMixin

NOTE_MAX_LENGTH = 200


class ReminderManualResend(UUIDPrimaryKeyMixin, TenantMixin, Base):
    """Un reenvío manual: actor, job y nota (sin `updated_at`, sin borrado)."""

    __tablename__ = "reminder_manual_resend"
    __table_args__ = (
        ForeignKeyConstraint(
            ["clinic_id", "appointment_id"],
            ["appointment.clinic_id", "appointment.id"],
            name="fk_reminder_manual_resend_appointment",
        ),
        ForeignKeyConstraint(
            ["clinic_id", "reminder_job_id"],
            ["reminder_job.clinic_id", "reminder_job.id"],
            name="fk_reminder_manual_resend_job",
        ),
        ForeignKeyConstraint(
            ["clinic_id", "actor_user_id"],
            ["user.clinic_id", "user.id"],
            name="fk_reminder_manual_resend_actor",
        ),
        CheckConstraint(
            f"note IS NULL OR char_length(note) <= {NOTE_MAX_LENGTH}", name="note_length"
        ),
        # Cooldown y tope diario por job (D6).
        Index(
            "ix_reminder_manual_resend_job",
            "clinic_id",
            "reminder_job_id",
            text("created_at DESC"),
        ),
        # Historial del turno en el timeline (D2/D3).
        Index(
            "ix_reminder_manual_resend_appointment",
            "clinic_id",
            "appointment_id",
            text("created_at DESC"),
        ),
    )

    appointment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reminder_job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # El servicio la fija con el reloj de la request (cooldown y día local, D6).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
