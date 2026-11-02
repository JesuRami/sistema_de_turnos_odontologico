"""Sillón/box de una clínica: recurso independiente del profesional (SU-04, C-02)."""

from sqlalchemy import Boolean, Index, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Chair(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """Sillón; la baja es `active=false` (sin borrado físico, regla 7)."""

    __tablename__ = "chair"
    __table_args__ = (
        # Habilita FK compuestas (clinic_id, chair_id) desde los hijos.
        UniqueConstraint("clinic_id", "id"),
        Index(None, "clinic_id", "active"),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
