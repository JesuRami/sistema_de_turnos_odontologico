"""Lista de espera (C-12, D1; RN-LE-01..05, Flujo 5).

- `WaitingListEntry`: quién espera, para qué profesional (NULL = "cualquiera"), en qué período de
  fechas locales y, opcional, en qué franja horaria y días de la semana. La base impide dos
  entradas `waiting/offered` del mismo paciente y profesional (`NULLS NOT DISTINCT`: "cualquiera"
  es un valor más, RN-LE-01).
- `WaitlistOffer`: un hueco exacto (profesional, sillón, inicio, fin) ofrecido a una entrada con
  vencimiento. A lo sumo una `pending` por entrada; `accepted` si y solo si tiene turno.
- `WaitlistEvent`: auditoría append-only (trigger, regla 7) sin PII (regla 13); el reporte de
  conversión la lee en vez del estado mutable (regla 8).

Todas con `clinic_id` y FKs compuestas intra-tenant (regla 4).
"""

import uuid
from datetime import date, datetime, time
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.appointment import pg_enum
from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    ActorType,
    WaitingListStatus,
    WaitlistEventType,
    WaitlistOfferStatus,
)

NOTES_MAX_LENGTH = 200
REASON_MAX_LENGTH = 200
ENTRY_SOURCES = ("reception", "online")
OFFER_MODES = ("auto", "manual")
ACTIVE_ENTRY_SQL = "status IN ('waiting', 'offered')"

WAITING_LIST_STATUS = pg_enum(WaitingListStatus, "waiting_list_status")
WAITLIST_OFFER_STATUS = pg_enum(WaitlistOfferStatus, "waitlist_offer_status")
WAITLIST_EVENT_TYPE = pg_enum(WaitlistEventType, "waitlist_event_type")


class WaitingListEntry(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """Una persona esperando un hueco en la clínica."""

    __tablename__ = "waiting_list_entry"
    __table_args__ = (
        # Habilita las FKs compuestas de `waitlist_offer` y `waitlist_event` (regla 4).
        UniqueConstraint("clinic_id", "id"),
        ForeignKeyConstraint(
            ["clinic_id", "patient_id"],
            ["patient.clinic_id", "patient.id"],
            name="fk_waiting_list_entry_patient",
        ),
        ForeignKeyConstraint(
            ["clinic_id", "professional_id"],
            ["professional.clinic_id", "professional.id"],
            name="fk_waiting_list_entry_professional",
        ),
        ForeignKeyConstraint(
            ["clinic_id", "created_by_user_id"],
            ["user.clinic_id", "user.id"],
            name="fk_waiting_list_entry_creator",
        ),
        CheckConstraint("date_to >= date_from", name="date_range"),
        CheckConstraint(
            "(time_from IS NULL AND time_to IS NULL) "
            "OR (time_from IS NOT NULL AND time_to IS NOT NULL AND time_to > time_from)",
            name="time_window",
        ),
        CheckConstraint(
            "weekdays IS NULL OR (cardinality(weekdays) BETWEEN 1 AND 7 "
            "AND weekdays <@ ARRAY[0, 1, 2, 3, 4, 5, 6]::smallint[])",
            name="weekdays_valid",
        ),
        CheckConstraint(
            f"notes IS NULL OR char_length(notes) <= {NOTES_MAX_LENGTH}", name="notes_length"
        ),
        CheckConstraint("consecutive_expired >= 0", name="consecutive_expired_nonneg"),
        CheckConstraint("source IN ('reception', 'online')", name="source_valid"),
        CheckConstraint(
            "(prioritized_at IS NULL) = (priority_reason IS NULL) "
            f"AND (priority_reason IS NULL OR char_length(priority_reason) <= {REASON_MAX_LENGTH})",
            name="priority_coherent",
        ),
        CheckConstraint(
            f"({ACTIVE_ENTRY_SQL}) OR closed_reason IS NOT NULL", name="closed_has_reason"
        ),
        # RN-LE-01: una entrada activa por paciente y profesional ("cualquiera" incluido).
        Index(
            "uq_waiting_list_entry_active",
            "clinic_id",
            "patient_id",
            "professional_id",
            unique=True,
            postgresql_where=text(ACTIVE_ENTRY_SQL),
            postgresql_nulls_not_distinct=True,
        ),
        # Orden de la cola y de la evaluación (D3/D10).
        Index(
            "ix_waiting_list_entry_queue",
            "clinic_id",
            text("prioritized_at NULLS LAST"),
            "created_at",
            "id",
            postgresql_where=text(ACTIVE_ENTRY_SQL),
        ),
        Index("ix_waiting_list_entry_patient", "clinic_id", "patient_id"),
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    professional_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    date_from: Mapped[date] = mapped_column(Date, nullable=False)
    date_to: Mapped[date] = mapped_column(Date, nullable=False)
    time_from: Mapped[time | None] = mapped_column(Time, nullable=True)
    time_to: Mapped[time | None] = mapped_column(Time, nullable=True)
    # 0 = lunes … 6 = domingo (como `schedule_rule.weekday`).
    weekdays: Mapped[list[int] | None] = mapped_column(ARRAY(SmallInteger), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[WaitingListStatus] = mapped_column(
        WAITING_LIST_STATUS, nullable=False, server_default=text("'waiting'")
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    prioritized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    priority_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_expired: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )
    # Código del cierre (`converted`, `range_elapsed`, `no_response`, `withdrawn_by_staff`…).
    closed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class WaitlistOffer(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """Un hueco ofrecido a una entrada, con vencimiento."""

    __tablename__ = "waitlist_offer"
    __table_args__ = (
        UniqueConstraint("clinic_id", "id"),
        ForeignKeyConstraint(
            ["clinic_id", "entry_id"],
            ["waiting_list_entry.clinic_id", "waiting_list_entry.id"],
            name="fk_waitlist_offer_entry",
        ),
        ForeignKeyConstraint(
            ["clinic_id", "professional_id"],
            ["professional.clinic_id", "professional.id"],
            name="fk_waitlist_offer_professional",
        ),
        ForeignKeyConstraint(
            ["clinic_id", "chair_id"],
            ["chair.clinic_id", "chair.id"],
            name="fk_waitlist_offer_chair",
        ),
        ForeignKeyConstraint(
            ["clinic_id", "source_appointment_id"],
            ["appointment.clinic_id", "appointment.id"],
            name="fk_waitlist_offer_source_appointment",
        ),
        ForeignKeyConstraint(
            ["clinic_id", "appointment_id"],
            ["appointment.clinic_id", "appointment.id"],
            name="fk_waitlist_offer_appointment",
        ),
        ForeignKeyConstraint(
            ["clinic_id", "created_by_user_id"],
            ["user.clinic_id", "user.id"],
            name="fk_waitlist_offer_creator",
        ),
        CheckConstraint("ends_at > starts_at", name="range_order"),
        CheckConstraint("expires_at <= starts_at", name="expires_before_start"),
        CheckConstraint("mode IN ('auto', 'manual')", name="mode_valid"),
        CheckConstraint(
            "(status = 'accepted') = (appointment_id IS NOT NULL)",
            name="accepted_has_appointment",
        ),
        # Una oferta pendiente por entrada (D1).
        Index(
            "uq_waitlist_offer_pending",
            "entry_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        # Vencimientos del tick (D4).
        Index(
            "ix_waitlist_offer_due",
            "expires_at",
            postgresql_where=text("status = 'pending'"),
        ),
        # Ofertas del mismo hueco (aceptación, D5) y "ya ofrecido a esta entrada" (D3).
        Index("ix_waitlist_offer_slot", "clinic_id", "professional_id", "starts_at"),
        Index("ix_waitlist_offer_entry", "clinic_id", "entry_id"),
    )

    entry_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    professional_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    chair_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[WaitlistOfferStatus] = mapped_column(
        WAITLIST_OFFER_STATUS, nullable=False, server_default=text("'pending'")
    )
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    source_appointment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    closed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class WaitlistEvent(UUIDPrimaryKeyMixin, Base):
    """Traza inmutable de la lista de espera (sin `updated_at`)."""

    __tablename__ = "waitlist_event"
    __table_args__ = (
        ForeignKeyConstraint(["clinic_id"], ["clinic.id"], name="fk_waitlist_event_clinic"),
        ForeignKeyConstraint(
            ["clinic_id", "entry_id"],
            ["waiting_list_entry.clinic_id", "waiting_list_entry.id"],
            name="fk_waitlist_event_entry",
        ),
        ForeignKeyConstraint(
            ["clinic_id", "offer_id"],
            ["waitlist_offer.clinic_id", "waitlist_offer.id"],
            name="fk_waitlist_event_offer",
        ),
        ForeignKeyConstraint(
            ["clinic_id", "actor_user_id"],
            ["user.clinic_id", "user.id"],
            name="fk_waitlist_event_actor",
        ),
        CheckConstraint(
            "actor_type <> 'user' OR actor_user_id IS NOT NULL", name="actor_user_coherent"
        ),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_is_object"),
        Index("ix_waitlist_event_entry", "clinic_id", "entry_id", "created_at"),
        Index("ix_waitlist_event_report", "clinic_id", "event", "created_at"),
        Index("ix_waitlist_event_offer", "offer_id", "created_at"),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    entry_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    offer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    event: Mapped[WaitlistEventType] = mapped_column(WAITLIST_EVENT_TYPE, nullable=False)
    actor_type: Mapped[ActorType] = mapped_column(pg_enum(ActorType, "actor_type"), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()"), nullable=False
    )
