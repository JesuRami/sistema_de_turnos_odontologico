"""Siembra de las plantillas por defecto de una clínica (C-09, D11).

Idempotente: `ON CONFLICT DO NOTHING` sobre `(clinic_id, channel, step)`, así reejecutar el seed
repone una plantilla faltante sin pisar el texto ni el estado que el admin haya editado.
"""

from __future__ import annotations

import uuid

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NotificationTemplate, ReminderChannel
from app.modules.reminders.templates import DEFAULT_TEMPLATES


async def seed_default_templates(session: AsyncSession, clinic_id: uuid.UUID) -> None:
    """Inserta las plantillas del catálogo que la clínica todavía no tenga."""
    await session.execute(
        pg_insert(NotificationTemplate)
        .values(
            [
                {
                    "clinic_id": clinic_id,
                    "channel": ReminderChannel(spec.channel),
                    "step": spec.step,
                    "meta_template_name": spec.meta_template_name,
                    "body_preview": spec.body_preview,
                }
                for spec in DEFAULT_TEMPLATES
            ]
        )
        .on_conflict_do_nothing(index_elements=["clinic_id", "channel", "step"])
    )
