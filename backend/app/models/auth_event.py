"""Evento de seguridad append-only (C-03).

La inmutabilidad no depende de privilegios: un trigger `BEFORE UPDATE OR
DELETE` la impone en la base. `clinic_id` es obligatorio y las referencias a
`user` son FKs compuestas `(clinic_id, id)`: un evento nunca apunta a un
usuario de otra clínica (regla dura 4). Sin PII en `payload` ni `subject_hash`
(solo huella del email normalizado cuando el sujeto es desconocido).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Index,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.enums import AuthEventType


class AuthEvent(UUIDPrimaryKeyMixin, Base):
    """Traza de seguridad inmutable (sin `updated_at`, sin borrado)."""

    __tablename__ = "auth_event"
    __table_args__ = (
        ForeignKeyConstraint(["clinic_id"], ["clinic.id"]),
        ForeignKeyConstraint(["clinic_id", "user_id"], ["user.clinic_id", "user.id"]),
        ForeignKeyConstraint(["clinic_id", "actor_user_id"], ["user.clinic_id", "user.id"]),
        CheckConstraint("jsonb_typeof(payload) IN ('object', 'array')", name="payload_is_json"),
        Index(None, "clinic_id", "created_at"),
        Index(None, "user_id", "created_at"),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    event: Mapped[AuthEventType] = mapped_column(
        Enum(
            AuthEventType,
            name="auth_event_type",
            native_enum=True,
            create_type=False,
            values_callable=lambda eventos: [e.value for e in eventos],
        ),
        nullable=False,
    )
    subject_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any] | list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
