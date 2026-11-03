"""Usuario del personal de la clínica (C-02: modelo; login/RBAC llegan en C-03)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import UserRole


class User(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """Usuario; la baja es `active=false` (sin borrado físico, regla 7)."""

    __tablename__ = "user"
    __table_args__ = (
        UniqueConstraint("clinic_id", "email"),
        # Habilita la FK compuesta de `auth_event` (C-03) y de futuros hijos.
        UniqueConstraint("clinic_id", "id"),
        ForeignKeyConstraint(
            ["clinic_id", "professional_id"], ["professional.clinic_id", "professional.id"]
        ),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        CheckConstraint(
            "role <> 'odontologo' OR professional_id IS NOT NULL",
            name="odontologo_requires_professional",
        ),
    )

    email: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(
            UserRole,
            name="user_role",
            native_enum=True,
            create_type=False,
            values_callable=lambda roles: [r.value for r in roles],
        ),
        nullable=False,
    )
    professional_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
