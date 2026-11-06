"""Outbox de respuestas de sesión de WhatsApp (C-10, D8; RN-WA-03).

El webhook nunca llama a Meta: deja aquí la respuesta que corresponde a un entrante y el worker
la envía como mensaje libre mientras siga abierta la ventana de 24 h (`expires_at`). `UNIQUE
(inbound_id, kind)` hace idempotente su creación ante reenvíos del webhook.

Regla 13: no guarda teléfono ni texto; el destinatario se lee de `patient.phone_e164` al enviar
y el texto sale del catálogo fijo por `kind`. `last_error` guarda solo un código.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
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
from app.models.enums import WhatsAppReplyKind, WhatsAppReplyStatus

WHATSAPP_REPLY_KIND = pg_enum(WhatsAppReplyKind, "whatsapp_reply_kind")
WHATSAPP_REPLY_STATUS = pg_enum(WhatsAppReplyStatus, "whatsapp_reply_status")


class WhatsAppOutboundReply(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """Una respuesta pendiente, enviada, vencida, salteada o fallida."""

    __tablename__ = "whatsapp_outbound_reply"
    __table_args__ = (
        UniqueConstraint("inbound_id", "kind"),
        # Nombre explícito: el generado supera los 63 caracteres de Postgres.
        ForeignKeyConstraint(
            ["clinic_id", "inbound_id"],
            ["whatsapp_inbound.clinic_id", "whatsapp_inbound.id"],
            name="fk_whatsapp_outbound_reply_inbound",
        ),
        ForeignKeyConstraint(["clinic_id", "patient_id"], ["patient.clinic_id", "patient.id"]),
        ForeignKeyConstraint(
            ["clinic_id", "appointment_id"],
            ["appointment.clinic_id", "appointment.id"],
            name="fk_whatsapp_outbound_reply_appointment",
        ),
        CheckConstraint("attempts >= 0", name="attempts_nonneg"),
        CheckConstraint("status <> 'sending' OR claimed_at IS NOT NULL", name="sending_has_claim"),
        CheckConstraint("status <> 'sent' OR sent_at IS NOT NULL", name="sent_has_sent_at"),
        CheckConstraint("char_length(last_error) <= 64", name="last_error_code"),
        Index(
            "ix_whatsapp_outbound_reply_due",
            "available_at",
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "ix_whatsapp_outbound_reply_claimed",
            "claimed_at",
            postgresql_where=text("status = 'sending'"),
        ),
    )

    inbound_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    kind: Mapped[WhatsAppReplyKind] = mapped_column(WHATSAPP_REPLY_KIND, nullable=False)
    status: Mapped[WhatsAppReplyStatus] = mapped_column(
        WHATSAPP_REPLY_STATUS, nullable=False, server_default=text("'pending'")
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Cierre de la ventana de 24 h del entrante: después no se puede enviar texto libre.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
