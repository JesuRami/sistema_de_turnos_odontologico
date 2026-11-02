"""Paciente liviano (SU-03): identificado por teléfono E.164, sin historia clínica (C-02)."""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, TenantMixin, UUIDPrimaryKeyMixin


class Patient(UUIDPrimaryKeyMixin, TenantMixin, CreatedAtMixin, Base):
    """Paciente; teléfono NO único (familias) y DNI opcional NO único."""

    __tablename__ = "patient"
    __table_args__ = (
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
