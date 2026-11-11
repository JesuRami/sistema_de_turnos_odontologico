"""Catálogo de estados del odontograma por clínica (C-15, Decisión 8, provisional).

Tabla operativa: `active` es mutable (un estado se desactiva, nunca se borra). En C-15 es de
solo lectura por API y se siembra desde `app.modules.clinical.catalog`.
"""

from sqlalchemy import Boolean, CheckConstraint, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin

CONDITION_SCOPES = ("surface", "tooth")


class OdontogramCondition(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """Estado registrable en una cara (`surface`) o en la pieza completa (`tooth`)."""

    __tablename__ = "odontogram_condition"
    __table_args__ = (
        UniqueConstraint("clinic_id", "id"),
        UniqueConstraint("clinic_id", "code"),
        CheckConstraint("scope IN ('surface', 'tooth')", name="scope_valid"),
        CheckConstraint("code ~ '^[a-z][a-z0-9_]{1,39}$'", name="code_format"),
        CheckConstraint("char_length(label) BETWEEN 1 AND 80", name="label_length"),
    )

    code: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
