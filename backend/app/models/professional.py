"""Profesional (odontólogo) de una clínica (C-02)."""

from sqlalchemy import Boolean, CheckConstraint, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin

DEFAULT_APPOINTMENT_MIN = 30


class Professional(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """Profesional; la baja es `active=false` (sin borrado físico, regla 7)."""

    __tablename__ = "professional"
    __table_args__ = (
        # Habilita FK compuestas (clinic_id, professional_id) desde los hijos.
        UniqueConstraint("clinic_id", "id"),
        CheckConstraint("default_duration_min > 0", name="default_duration_positive"),
        CheckConstraint("buffer_min >= 0", name="buffer_nonneg"),
        Index(None, "clinic_id", "active"),
    )

    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    color: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_duration_min: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text(str(DEFAULT_APPOINTMENT_MIN))
    )
    buffer_min: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    booking_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
