"""Paciente liviano (SU-03): identificado por teléfono E.164, sin historia clínica (C-02).

C-06: un duplicado se fusiona en otro (`merged_into_patient_id`) y queda archivado; nunca
se borra (regla 7). La auditoría de la fusión vive en `patient_merge`.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
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

from app.models.base import Base, CreatedAtMixin, TenantMixin, UUIDPrimaryKeyMixin


class Patient(UUIDPrimaryKeyMixin, TenantMixin, CreatedAtMixin, Base):
    """Paciente; teléfono NO único (familias) y DNI opcional NO único."""

    __tablename__ = "patient"
    __table_args__ = (
        # Habilita la FK compuesta (clinic_id, patient_id) desde `appointment` (C-05). Orden
        # `(id, clinic_id)`: no compite con los índices que filtran por clínica.
        UniqueConstraint("id", "clinic_id"),
        # Fusión de duplicados (C-06): el fusionado apunta a uno de su misma clínica.
        ForeignKeyConstraint(
            ["merged_into_patient_id", "clinic_id"], ["patient.id", "patient.clinic_id"]
        ),
        CheckConstraint("merged_into_patient_id <> id", name="not_merged_into_self"),
        CheckConstraint(
            "merged_into_patient_id IS NULL OR archived_at IS NOT NULL", name="merged_is_archived"
        ),
        CheckConstraint("btrim(full_name) <> ''", name="full_name_not_blank"),
        CheckConstraint("phone_e164 IS NOT NULL OR email IS NOT NULL", name="contact_required"),
        CheckConstraint(
            "phone_e164 IS NULL OR phone_e164 ~ '^\\+[1-9][0-9]{7,14}$'", name="phone_e164_format"
        ),
        # Versión del texto aceptado implica fecha de aceptación (Ley 25.326 / 26.529 / 27.706).
        CheckConstraint(
            "privacy_consent_version IS NULL OR privacy_consent_at IS NOT NULL",
            name="consent_coherent",
        ),
        Index(None, "clinic_id", "phone_e164"),
        Index(
            "ix_patient_full_name_trgm",
            "full_name",
            postgresql_using="gin",
            postgresql_ops={"full_name": "gin_trgm_ops"},
        ),
    )

    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    phone_e164: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    dni: Mapped[str | None] = mapped_column(Text, nullable=True)
    whatsapp_opt_in: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    privacy_consent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    privacy_consent_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Baja lógica (regla 7): el paciente archivado queda fuera de las búsquedas.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Fusión asistida (C-06): ficha conservada; implica `archived_at` (CHECK).
    merged_into_patient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
