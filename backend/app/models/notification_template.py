"""Plantilla de notificación por clínica, canal y paso (C-09, D1/D11, RN-WA-02).

`meta_template_name` es el nombre aprobado en Meta (WhatsApp) o una clave interna (email);
`body_preview` solo lleva variables `{{nombre}}`-style, nunca datos personales (regla 13).
"""

from sqlalchemy import Boolean, CheckConstraint, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.appointment import pg_enum
from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ReminderChannel

REMINDER_CHANNEL = pg_enum(ReminderChannel, "reminder_channel")
# C-12: `waitlist_offer` es el paso del envío de una oferta de la lista de espera.
STEP_FORMAT_SQL = "step ~ '^(created|waitlist_offer|t_[0-9]+h)$'"


class NotificationTemplate(UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    """Una plantilla activa o no por `(clinic_id, channel, step)`."""

    __tablename__ = "notification_template"
    __table_args__ = (
        # Habilita la FK compuesta de `reminder_job` (regla 4).
        UniqueConstraint("clinic_id", "id"),
        UniqueConstraint("clinic_id", "channel", "step"),
        CheckConstraint(STEP_FORMAT_SQL, name="step_format"),
        CheckConstraint("locale = 'es_AR'", name="locale_es_ar"),
        CheckConstraint("btrim(meta_template_name) <> ''", name="name_not_blank"),
        CheckConstraint("btrim(body_preview) <> ''", name="body_not_blank"),
    )

    channel: Mapped[ReminderChannel] = mapped_column(REMINDER_CHANNEL, nullable=False)
    step: Mapped[str] = mapped_column(Text, nullable=False)
    meta_template_name: Mapped[str] = mapped_column(Text, nullable=False)
    locale: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'es_AR'"))
    body_preview: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
