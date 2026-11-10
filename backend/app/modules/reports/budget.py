"""Alerta de costo mensual de WhatsApp (C-14, D8; SU-07, RN-WA-05).

Mes local de la clínica en curso: suma de `payload.cost_micros` de los `delivery_event` `sent`
de jobs del canal WhatsApp (misma fuente que el reporte de C-10, regla 8), contra el umbral
`clinic.whatsapp_monthly_alert_micros`. Solo informa: **no corta envíos** (CHANGES C-14).
"""

from __future__ import annotations

import uuid
from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import BigInteger, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Clinic, DeliveryEvent, DeliveryEventType, ReminderChannel, ReminderJob
from app.modules.reports.schemas import WhatsAppBudget, WhatsAppBudgetStatus
from app.modules.reports.whatsapp import usd

WARNING_RATIO = Decimal("0.80")


def month_bounds(now: datetime, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """`[1.º del mes 00:00, 1.º del mes siguiente 00:00)` en la zona de la clínica."""
    local = now.astimezone(tz)
    inicio = datetime.combine(local.date().replace(day=1), time.min, tzinfo=tz)
    anio, mes = (inicio.year + 1, 1) if inicio.month == 12 else (inicio.year, inicio.month + 1)
    return inicio, inicio.replace(year=anio, month=mes)


def budget_status(spent: int, threshold: int | None) -> tuple[WhatsAppBudgetStatus, float | None]:
    if threshold is None:
        return "disabled", None
    ratio = Decimal(spent) / Decimal(threshold)
    porcentaje = float(round(ratio * 100, 2))
    if ratio >= 1:
        return "exceeded", porcentaje
    if ratio >= WARNING_RATIO:
        return "warning", porcentaje
    return "ok", porcentaje


async def whatsapp_budget(
    session: AsyncSession, clinic_id: uuid.UUID, now: datetime
) -> WhatsAppBudget:
    fila = (
        await session.execute(
            select(Clinic.timezone, Clinic.whatsapp_monthly_alert_micros).where(
                Clinic.id == clinic_id
            )
        )
    ).one()
    tz = ZoneInfo(fila.timezone)
    inicio, fin = month_bounds(now, tz)
    gastado = await session.scalar(
        select(
            func.coalesce(
                func.sum(cast(DeliveryEvent.payload["cost_micros"].astext, BigInteger)), 0
            )
        )
        .join(
            ReminderJob,
            (ReminderJob.id == DeliveryEvent.reminder_job_id)
            & (ReminderJob.clinic_id == DeliveryEvent.clinic_id),
        )
        .where(
            DeliveryEvent.clinic_id == clinic_id,
            DeliveryEvent.event_type == DeliveryEventType.SENT,
            DeliveryEvent.occurred_at >= inicio,
            DeliveryEvent.occurred_at < fin,
            ReminderJob.channel == ReminderChannel.WHATSAPP,
        )
    )
    spent = int(gastado or 0)
    umbral = fila.whatsapp_monthly_alert_micros
    estado, porcentaje = budget_status(spent, umbral)
    return WhatsAppBudget(
        month=inicio.strftime("%Y-%m"),
        spent_usd=usd(spent),
        threshold_usd=usd(umbral) if umbral is not None else None,
        used_pct=porcentaje,
        status=estado,
    )
