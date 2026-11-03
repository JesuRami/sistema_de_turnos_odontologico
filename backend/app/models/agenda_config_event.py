"""Auditoría append-only de la configuración de agenda (C-04, US-001 CA-3).

Igual que `auth_event`, la inmutabilidad la impone un trigger `BEFORE UPDATE OR
DELETE`. `changes` guarda `{campo: [anterior, nuevo]}`; la configuración no
contiene datos de pacientes (regla 13).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKeyConstraint, Index, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.enums import ConfigAction, ConfigEntity


class AgendaConfigEvent(UUIDPrimaryKeyMixin, Base):
    """Traza inmutable de una mutación de configuración (sin `updated_at`)."""

    __tablename__ = "agenda_config_event"
    __table_args__ = (
        ForeignKeyConstraint(["clinic_id"], ["clinic.id"]),
        ForeignKeyConstraint(["clinic_id", "actor_user_id"], ["user.clinic_id", "user.id"]),
        CheckConstraint("jsonb_typeof(changes) = 'object'", name="changes_is_object"),
        Index(None, "clinic_id", "created_at"),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    entity: Mapped[ConfigEntity] = mapped_column(
        Enum(
            ConfigEntity,
            name="config_entity",
            native_enum=True,
            create_type=False,
            values_callable=lambda valores: [v.value for v in valores],
        ),
        nullable=False,
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[ConfigAction] = mapped_column(
        Enum(
            ConfigAction,
            name="config_action",
            native_enum=True,
            create_type=False,
            values_callable=lambda valores: [v.value for v in valores],
        ),
        nullable=False,
    )
    changes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # `clock_timestamp()` (no `now()`): ordena también los eventos de una misma transacción.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("clock_timestamp()"), nullable=False
    )
