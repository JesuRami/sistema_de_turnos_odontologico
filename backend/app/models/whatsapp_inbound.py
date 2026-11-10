"""Mensaje entrante de WhatsApp ya procesado, append-only (C-10, D1/D7; RN-WA-03).

Una fila por clínica a la que se atribuyó el mensaje: con número compartido, un STOP sin contexto
puede afectar a varias, y por eso la unicidad es `(clinic_id, provider_message_id)`. Sirve para
deduplicar los reenvíos de Meta y para calcular la ventana de 24 h del paciente.

Regla 13: NO guarda el texto del mensaje ni el teléfono del remitente; solo la intención
clasificada, el número receptor (dato de la clínica) y los ids resueltos. La inmutabilidad la
impone un trigger `BEFORE UPDATE OR DELETE`, como en `appointment_event`.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.appointment import pg_enum
from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.enums import WhatsAppIntent

WHATSAPP_INTENT = pg_enum(WhatsAppIntent, "whatsapp_intent")
ROUTED_BY = ("context", "phone")


class WhatsAppInbound(UUIDPrimaryKeyMixin, Base):
    """Entrante clasificado y atribuido a una clínica (sin `updated_at`, sin borrado)."""

    __tablename__ = "whatsapp_inbound"
    __table_args__ = (
        UniqueConstraint("clinic_id", "provider_message_id"),
        # Habilita la FK compuesta de `whatsapp_outbound_reply` (regla 4).
        UniqueConstraint("clinic_id", "id"),
        ForeignKeyConstraint(["clinic_id"], ["clinic.id"]),
        ForeignKeyConstraint(["clinic_id", "patient_id"], ["patient.clinic_id", "patient.id"]),
        ForeignKeyConstraint(
            ["clinic_id", "appointment_id"], ["appointment.clinic_id", "appointment.id"]
        ),
        # C-12 (D8): respuesta a una oferta de la lista de espera.
        ForeignKeyConstraint(
            ["clinic_id", "waitlist_offer_id"],
            ["waitlist_offer.clinic_id", "waitlist_offer.id"],
            name="fk_whatsapp_inbound_offer",
        ),
        CheckConstraint("routed_by IN ('context', 'phone')", name="routed_by"),
        CheckConstraint("btrim(provider_message_id) <> ''", name="provider_message_id_not_blank"),
        # Ventana de 24 h: último entrante del paciente en la clínica.
        Index(
            "ix_whatsapp_inbound_clinic_patient_received",
            "clinic_id",
            "patient_id",
            text("received_at DESC"),
        ),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    provider_message_id: Mapped[str] = mapped_column(Text, nullable=False)
    # `phone_number_id` de Meta que recibió el mensaje (dato de la clínica, no del paciente).
    phone_number_id: Mapped[str] = mapped_column(Text, nullable=False)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    waitlist_offer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    intent: Mapped[WhatsAppIntent] = mapped_column(WHATSAPP_INTENT, nullable=False)
    routed_by: Mapped[str] = mapped_column(Text, nullable=False)
    # Instante informado por Meta (`timestamp` del mensaje).
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()"), nullable=False
    )
