"""Job de recordatorio persistente (C-09, D1; DD-06, RN-WA-04).

La clave `(appointment_id, step, channel)` es la idempotencia del envío: la impone la base, así
que un doble tick o un reintento de programación nunca duplica un mensaje. `scheduled_for` es la
hora calculada y `available_at` cuándo se puede reclamar (el backoff la empuja); `status =
sending` es el lease del reclamo. `last_error` guarda solo un código, jamás el mensaje del
proveedor (puede traer el teléfono, regla 13).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.appointment import pg_enum
from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ReminderChannel, ReminderStatus
from app.models.notification_template import REMINDER_CHANNEL, STEP_FORMAT_SQL

REMINDER_STATUS = pg_enum(ReminderStatus, "reminder_status")


class ReminderJob(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """Un mensaje programado de un turno: paso, canal, estado e intentos."""

    __tablename__ = "reminder_job"
    __table_args__ = (
        # Habilita la FK compuesta de `delivery_event` (regla 4).
        UniqueConstraint("clinic_id", "id"),
        # Idempotencia del motor (RN-WA-04): un job por turno, paso y canal.
        UniqueConstraint("appointment_id", "step", "channel"),
        ForeignKeyConstraint(
            ["clinic_id", "appointment_id"], ["appointment.clinic_id", "appointment.id"]
        ),
        # C-12 (D2): un job es de un turno o de una oferta de la lista de espera, nunca ambos.
        ForeignKeyConstraint(
            ["clinic_id", "waitlist_offer_id"],
            ["waitlist_offer.clinic_id", "waitlist_offer.id"],
            name="fk_reminder_job_offer",
        ),
        CheckConstraint("num_nonnulls(appointment_id, waitlist_offer_id) = 1", name="one_target"),
        CheckConstraint(
            "(step = 'waitlist_offer') = (waitlist_offer_id IS NOT NULL)", name="offer_step"
        ),
        Index(
            "uq_reminder_job_offer_channel",
            "waitlist_offer_id",
            "channel",
            unique=True,
            postgresql_where=text("waitlist_offer_id IS NOT NULL"),
        ),
        ForeignKeyConstraint(
            ["clinic_id", "template_id"],
            ["notification_template.clinic_id", "notification_template.id"],
        ),
        CheckConstraint(STEP_FORMAT_SQL, name="step_format"),
        CheckConstraint("attempts >= 0", name="attempts_nonneg"),
        CheckConstraint("cost_micros IS NULL OR cost_micros >= 0", name="cost_nonneg"),
        CheckConstraint("status <> 'sending' OR claimed_at IS NOT NULL", name="sending_has_claim"),
        CheckConstraint(
            "status NOT IN ('sent', 'delivered', 'read') OR sent_at IS NOT NULL",
            name="sent_has_sent_at",
        ),
        CheckConstraint("char_length(last_error) <= 64", name="last_error_code"),
        # Cola del tick: solo lo reclamable, ordenado por disponibilidad.
        Index(
            "ix_reminder_job_due",
            "available_at",
            postgresql_where=text("status = 'scheduled'"),
        ),
        # Leases vencidos de un worker caído.
        Index(
            "ix_reminder_job_claimed",
            "claimed_at",
            postgresql_where=text("status = 'sending'"),
        ),
        # Agregado de costo y envíos por clínica y paso (RN-WA-05).
        Index("ix_reminder_job_clinic_step_sent", "clinic_id", "step", "sent_at"),
        # Lista de seguimiento: fallos de entrega por clínica (C-11, D8).
        Index(
            "ix_reminder_job_failed",
            "clinic_id",
            "scheduled_for",
            postgresql_where=text("status = 'failed'"),
        ),
        # Búsqueda del webhook por el id de Meta (C-10, D1/D6); los ids del proveedor son únicos.
        Index(
            "uq_reminder_job_provider_message_id",
            "provider_message_id",
            unique=True,
            postgresql_where=text("provider_message_id IS NOT NULL"),
        ),
    )

    # NULL en un job de oferta (C-12, D2): entonces `waitlist_offer_id` está.
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    waitlist_offer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    step: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[ReminderChannel] = mapped_column(REMINDER_CHANNEL, nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    starts_at_snapshot: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[ReminderStatus] = mapped_column(
        REMINDER_STATUS, nullable=False, server_default=text("'scheduled'")
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_micros: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Último reenvío manual pendiente (C-11, D5): el recálculo no lo cancela por paso vencido.
    # Se limpia cuando el job sale de `scheduled`.
    manual_resend_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
