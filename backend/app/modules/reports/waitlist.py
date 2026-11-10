"""Reporte de conversión de la lista de espera (C-12, D9; spec waitlist/conversion-report; US-050).

- **Cohorte**: las ofertas de la clínica con evento `offer_created` en el rango local
  `[from 00:00, to+1 00:00)`. Profesional y modo salen del payload de ese evento.
- **Resultado**: el último evento terminal de cada oferta (`offer_accepted`, `offer_declined`,
  `offer_expired`, `offer_cancelled`); sin ninguno, la oferta sigue pendiente y cuenta solo en
  creadas.
- **Regla 8**: todo sobre `waitlist_event` (append-only), nunca sobre `waitlist_offer.status`.

Filas: cada profesional activo de la clínica (y cualquiera con ofertas en el rango), más el total.
La tasa es `aceptadas / creadas` en %, con un decimal, `null` sin ofertas. Sin datos de pacientes.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Professional, WaitlistEvent, WaitlistEventType
from app.modules.reports.schemas import WaitlistReport, WaitlistReportRow, WaitlistReportTotals
from app.modules.reports.service import ReportWindow

_TERMINALES = (
    WaitlistEventType.OFFER_ACCEPTED,
    WaitlistEventType.OFFER_DECLINED,
    WaitlistEventType.OFFER_EXPIRED,
    WaitlistEventType.OFFER_CANCELLED,
)
_COLUMNA = {
    WaitlistEventType.OFFER_ACCEPTED: "accepted",
    WaitlistEventType.OFFER_DECLINED: "declined",
    WaitlistEventType.OFFER_EXPIRED: "expired",
    WaitlistEventType.OFFER_CANCELLED: "cancelled",
}


def conversion_pct(accepted: int, created: int) -> float | None:
    return round(accepted / created * 100, 1) if created else None


async def waitlist_report(
    session: AsyncSession, clinic_id: uuid.UUID, w: ReportWindow
) -> WaitlistReport:
    creado = WaitlistEvent
    cohorte = (
        select(
            creado.offer_id.label("offer_id"),
            creado.payload["professional_id"].astext.label("professional_id"),
            creado.payload["mode"].astext.label("mode"),
        )
        .where(
            creado.clinic_id == clinic_id,
            creado.event == WaitlistEventType.OFFER_CREATED,
            creado.offer_id.is_not(None),
            creado.created_at >= w.start_at,
            creado.created_at < w.end_at,
        )
        .cte("cohorte")
    )
    final = (
        select(WaitlistEvent.offer_id.label("offer_id"), WaitlistEvent.event.label("event"))
        .where(
            WaitlistEvent.clinic_id == clinic_id,
            WaitlistEvent.event.in_(_TERMINALES),
            WaitlistEvent.offer_id.in_(select(cohorte.c.offer_id)),
        )
        .order_by(WaitlistEvent.offer_id, WaitlistEvent.created_at.desc(), WaitlistEvent.id.desc())
        .distinct(WaitlistEvent.offer_id)
        .cte("final")
    )
    filas = (
        await session.execute(
            select(
                cohorte.c.professional_id,
                func.count().label("created"),
                func.count().filter(cohorte.c.mode == "manual").label("manual"),
                *(
                    func.count().filter(final.c.event == evento).label(columna)
                    for evento, columna in _COLUMNA.items()
                ),
            )
            .select_from(cohorte)
            .outerjoin(final, final.c.offer_id == cohorte.c.offer_id)
            .group_by(cohorte.c.professional_id)
        )
    ).all()
    datos: dict[str, Any] = {f.professional_id: f for f in filas}
    profesionales = (
        await session.execute(
            select(Professional.id, Professional.display_name)
            .where(
                Professional.clinic_id == clinic_id,
                or_(
                    Professional.active.is_(True),
                    cast(Professional.id, String).in_(list(datos)),
                ),
            )
            .order_by(Professional.display_name, Professional.id)
        )
    ).all()
    rows: list[WaitlistReportRow] = []
    for prof_id, nombre in profesionales:
        f = datos.get(str(prof_id))
        creadas = int(f.created) if f else 0
        aceptadas = int(f.accepted) if f else 0
        rows.append(
            WaitlistReportRow(
                professional_id=prof_id,
                professional_name=nombre,
                created=creadas,
                auto=creadas - (int(f.manual) if f else 0),
                manual=int(f.manual) if f else 0,
                accepted=aceptadas,
                declined=int(f.declined) if f else 0,
                expired=int(f.expired) if f else 0,
                cancelled=int(f.cancelled) if f else 0,
                conversion_pct=conversion_pct(aceptadas, creadas),
            )
        )
    creadas = sum(r.created for r in rows)
    aceptadas = sum(r.accepted for r in rows)
    return WaitlistReport(
        from_date=w.first_day,
        to_date=w.last_day,
        rows=rows,
        totals=WaitlistReportTotals(
            created=creadas,
            auto=sum(r.auto for r in rows),
            manual=sum(r.manual for r in rows),
            accepted=aceptadas,
            declined=sum(r.declined for r in rows),
            expired=sum(r.expired for r in rows),
            cancelled=sum(r.cancelled for r in rows),
            conversion_pct=conversion_pct(aceptadas, creadas),
        ),
    )
