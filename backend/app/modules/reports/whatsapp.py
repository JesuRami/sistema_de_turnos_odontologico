"""Reporte de mensajes de recordatorio y su costo por paso (C-10, D10; RN-WA-05).

- **Cohorte**: los jobs de la clínica con un evento `sent` cuyo instante cae en el rango local
  `[from 00:00, to+1 00:00)` de la clínica.
- **Enviados por evento** (C-11, D9): cada `sent` del rango cuenta, incluidos los reenvíos
  manuales del mismo job.
- **Por job** (una vez, aunque se haya reenviado): entregado si tiene `delivered` o `read`; leído si
  tiene `read`; fallido solo si el último intento falló: un `failed` posterior al último `sent`
  (truncado al segundo, porque Meta informa con segundos enteros). Una falla vieja ya reenviada no
  cuenta. El paso y el canal se leen del job (no cambian desde que se crea).
- **Costo sobre eventos** (regla 8): la suma de `payload.cost_micros` de los eventos `sent` del
  rango. No se lee el estado mutable del job.
- Filas: `created` + los pasos configurados de la clínica (y cualquier otro paso con envíos), por
  canal `whatsapp` y `email`, con 0 si no hubo; más `totals`.

Sin datos personales ni ids del proveedor en la salida.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import BigInteger, and_, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Clinic, DeliveryEvent, DeliveryEventType, ReminderChannel, ReminderJob
from app.modules.reminders.scheduling import step_for_offset
from app.modules.reminders.templates import STEP_CREATED
from app.modules.reports.schemas import WhatsAppReport, WhatsAppReportRow, WhatsAppReportTotals
from app.modules.reports.service import ReportWindow

_MICROS = Decimal(1_000_000)
_CHANNELS = (ReminderChannel.WHATSAPP, ReminderChannel.EMAIL)


def usd(micros: int) -> str:
    """`12500` → `"0.012500"` (USD con 6 decimales, sin redondeo binario)."""
    return str((Decimal(micros) / _MICROS).quantize(Decimal("0.000001")))


async def _configured_steps(session: AsyncSession, clinic_id: uuid.UUID) -> list[str]:
    pasos = await session.scalar(select(Clinic.reminder_steps).where(Clinic.id == clinic_id))
    offsets: set[int] = set()
    for entrada in pasos or []:
        try:
            offset = int(entrada["offset_h"])
        except (KeyError, TypeError, ValueError):
            continue
        if offset > 0:
            offsets.add(offset)
    return [STEP_CREATED] + [step_for_offset(o) for o in sorted(offsets, reverse=True)]


async def whatsapp_report(
    session: AsyncSession, clinic_id: uuid.UUID, w: ReportWindow
) -> WhatsAppReport:
    enviado = DeliveryEvent
    cohorte = (
        select(
            enviado.reminder_job_id.label("job_id"),
            func.count().label("sends"),
            func.date_trunc("second", func.max(enviado.occurred_at)).label("last_sent"),
            func.coalesce(
                func.sum(cast(enviado.payload["cost_micros"].astext, BigInteger)), 0
            ).label("cost"),
        )
        .where(
            enviado.clinic_id == clinic_id,
            enviado.event_type == DeliveryEventType.SENT,
            enviado.occurred_at >= w.start_at,
            enviado.occurred_at < w.end_at,
        )
        .group_by(enviado.reminder_job_id)
        .cte("cohorte")
    )
    otro = DeliveryEvent.__table__.alias("otro")
    por_job = (
        select(
            cohorte.c.job_id,
            cohorte.c.sends,
            cohorte.c.cost,
            func.coalesce(
                func.bool_or(
                    otro.c.event_type.in_([DeliveryEventType.DELIVERED, DeliveryEventType.READ])
                ),
                False,
            ).label("delivered"),
            func.coalesce(func.bool_or(otro.c.event_type == DeliveryEventType.READ), False).label(
                "read"
            ),
            func.coalesce(
                func.bool_or(
                    and_(
                        otro.c.event_type == DeliveryEventType.FAILED,
                        otro.c.occurred_at >= cohorte.c.last_sent,
                    )
                ),
                False,
            ).label("failed"),
        )
        .select_from(cohorte)
        .outerjoin(
            otro,
            and_(otro.c.clinic_id == clinic_id, otro.c.reminder_job_id == cohorte.c.job_id),
        )
        .group_by(cohorte.c.job_id, cohorte.c.sends, cohorte.c.cost, cohorte.c.last_sent)
        .cte("por_job")
    )
    filas = (
        await session.execute(
            select(
                ReminderJob.step,
                ReminderJob.channel,
                func.coalesce(func.sum(por_job.c.sends), 0).label("sent"),
                func.count().filter(por_job.c.delivered).label("delivered"),
                func.count().filter(por_job.c.read).label("read"),
                func.count().filter(por_job.c.failed).label("failed"),
                func.coalesce(func.sum(por_job.c.cost), 0).label("cost"),
            )
            .select_from(por_job)
            .join(
                ReminderJob,
                and_(ReminderJob.clinic_id == clinic_id, ReminderJob.id == por_job.c.job_id),
            )
            .group_by(ReminderJob.step, ReminderJob.channel)
        )
    ).all()
    datos = {(f.step, f.channel): f for f in filas}
    pasos = await _configured_steps(session, clinic_id)
    pasos += sorted({paso for paso, _ in datos} - set(pasos))
    rows: list[WhatsAppReportRow] = []
    for paso in pasos:
        for canal in _CHANNELS:
            f = datos.get((paso, canal))
            rows.append(
                WhatsAppReportRow(
                    step=paso,
                    channel=canal,
                    sent=int(f.sent) if f else 0,
                    delivered=f.delivered if f else 0,
                    read=f.read if f else 0,
                    failed=f.failed if f else 0,
                    cost_usd=usd(int(f.cost) if f else 0),
                )
            )
    costo_total = sum(int(f.cost) for f in filas)
    return WhatsAppReport(
        from_date=w.first_day,
        to_date=w.last_day,
        rows=rows,
        totals=WhatsAppReportTotals(
            sent=sum(r.sent for r in rows),
            delivered=sum(r.delivered for r in rows),
            read=sum(r.read for r in rows),
            failed=sum(r.failed for r in rows),
            cost_usd=usd(costo_total),
        ),
    )
