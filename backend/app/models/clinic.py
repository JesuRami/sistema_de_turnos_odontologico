"""Clínica (tenant) con su configuración operativa (C-02)."""

from typing import Any

from sqlalchemy import Boolean, CheckConstraint, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

DEFAULT_TIMEZONE = "America/Argentina/Buenos_Aires"
DEFAULT_CANCELLATION_WINDOW_HOURS = 24
DEFAULT_REMINDER_STEPS_SQL = (
    '\'[{"offset_h": 72, "channel": "whatsapp"}, {"offset_h": 24, "channel": "whatsapp"}, '
    '{"offset_h": 3, "channel": "whatsapp"}]\'::jsonb'
)


class Clinic(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Tenant: `slug` único global (URL pública de reserva)."""

    __tablename__ = "clinic"
    __table_args__ = (
        UniqueConstraint("slug"),
        CheckConstraint("cancellation_window_hours >= 0", name="cancellation_window_nonneg"),
        CheckConstraint("jsonb_typeof(reminder_steps) = 'array'", name="reminder_steps_array"),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    timezone: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text(f"'{DEFAULT_TIMEZONE}'")
    )
    booking_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    cancellation_window_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text(str(DEFAULT_CANCELLATION_WINDOW_HOURS))
    )
    reminder_steps: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text(DEFAULT_REMINDER_STEPS_SQL)
    )
