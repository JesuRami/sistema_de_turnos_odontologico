"""Reportes sobre `appointment_event` (C-13, US-050).

Regla de oro (US-050 CA-3, regla 8): el estado de un turno es el de su **último
evento**; nunca se lee `appointment.status`. El rango filtra por la fecha del
turno (instantánea del último evento) en la zona de la clínica (RN-GL-03).

Para poder usar el índice `(clinic_id, slot_starts_at)` sin equivocarse con los
turnos reprogramados, primero se buscan los turnos con *algún* evento dentro del
rango, luego se toma el último evento de cada uno y recién ahí se vuelve a
filtrar por su horario final.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import CTE, and_, exists, extract, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.expression import Subquery

from app.common.exceptions import DomainError
from app.models import (
    VIGENT_STATUSES,
    AppointmentEvent,
    AppointmentEventType,
    AppointmentStatus,
    Block,
    CancellationReason,
    Chair,
    Clinic,
    Professional,
    ScheduleRule,
)
from app.modules.agenda.availability import RuleWindow
from app.modules.reports.capacity import BlockSpan, RuleCapacity, capacity_minutes
from app.modules.reports.schemas import (
    AbsenteeismReport,
    AbsenteeismRow,
    AbsenteeismTotals,
    CancellationRow,
    CancellationsReport,
    OccupancyReport,
    OccupancyRow,
    OccupancyTotals,
)

MAX_RANGE_DAYS = 366
_EVENT = AppointmentEvent


@dataclass(frozen=True, slots=True)
class ReportWindow:
    """Rango `[from, to]` inclusive por día local, como instantes `[start_at, end_at)`."""

    tz: ZoneInfo
    first_day: date
    last_day: date
    start_at: datetime
    end_at: datetime


def _rate(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0


def _pct(booked: int, capacity: int) -> float:
    return round(booked / capacity * 100, 2) if capacity else 0.0


class ReportsService:
    """Lógica de reportes; los routers solo validan y delegan aquí."""

    def __init__(self, session: AsyncSession, clinic_id: uuid.UUID) -> None:
        self.session = session
        self.clinic_id = clinic_id

    # ------------------------------------------------------------ base común

    async def window(self, desde: date, hasta: date) -> ReportWindow:
        if desde > hasta:
            raise DomainError(422, "invalid_range")
        if (hasta - desde).days + 1 > MAX_RANGE_DAYS:
            raise DomainError(422, "range_too_large")
        zona = await self.session.scalar(select(Clinic.timezone).where(Clinic.id == self.clinic_id))
        tz = ZoneInfo(zona or "America/Argentina/Buenos_Aires")
        return ReportWindow(
            tz=tz,
            first_day=desde,
            last_day=hasta,
            start_at=datetime.combine(desde, time.min, tzinfo=tz),
            end_at=datetime.combine(hasta + timedelta(days=1), time.min, tzinfo=tz),
        )

    def _final(self, w: ReportWindow) -> CTE:
        """Un renglón por turno: su último evento (D1) con el horario dentro del rango."""
        ev = _EVENT
        candidatos = select(ev.appointment_id).where(
            ev.clinic_id == self.clinic_id,
            ev.slot_starts_at >= w.start_at,
            ev.slot_starts_at < w.end_at,
        )
        ultimo = (
            select(
                ev.appointment_id.label("appointment_id"),
                ev.to_status.label("status"),
                ev.professional_id.label("professional_id"),
                ev.chair_id.label("chair_id"),
                ev.slot_starts_at.label("slot_starts_at"),
                ev.slot_ends_at.label("slot_ends_at"),
            )
            .where(ev.clinic_id == self.clinic_id, ev.appointment_id.in_(candidatos))
            .distinct(ev.appointment_id)
            .order_by(ev.appointment_id, ev.created_at.desc(), ev.id.desc())
            .subquery("ultimo")
        )
        alta = aliased(AppointmentEvent)
        es_sobreturno = exists().where(
            alta.clinic_id == self.clinic_id,
            alta.appointment_id == ultimo.c.appointment_id,
            alta.event == AppointmentEventType.OVERBOOKING_CREATED,
        )
        return (
            select(
                ultimo.c.appointment_id,
                ultimo.c.status,
                ultimo.c.professional_id,
                ultimo.c.chair_id,
                ultimo.c.slot_starts_at,
                ultimo.c.slot_ends_at,
                es_sobreturno.label("is_overbooking"),
            )
            .where(ultimo.c.slot_starts_at >= w.start_at, ultimo.c.slot_starts_at < w.end_at)
            .cte("final")
        )

    def _cancel_events(self, final: CTE) -> Subquery:
        """Último `cancelled` de los turnos cuyo estado final es `cancelled`."""
        ev = _EVENT
        cancelados = select(final.c.appointment_id).where(
            final.c.status == AppointmentStatus.CANCELLED
        )
        return (
            select(
                ev.appointment_id.label("appointment_id"),
                ev.payload["reason"].as_string().label("reason"),
                ev.payload["late"].as_boolean().label("late"),
            )
            .where(
                ev.clinic_id == self.clinic_id,
                ev.event == AppointmentEventType.CANCELLED,
                ev.appointment_id.in_(cancelados),
            )
            .distinct(ev.appointment_id)
            .order_by(ev.appointment_id, ev.created_at.desc(), ev.id.desc())
            .subquery("cancelacion")
        )

    async def _names(
        self, model: type[Professional] | type[Chair], ids: set[uuid.UUID]
    ) -> dict[uuid.UUID, str]:
        if not ids:
            return {}
        nombre = Professional.display_name if model is Professional else Chair.name
        filas = await self.session.execute(
            select(model.id, nombre).where(model.clinic_id == self.clinic_id, model.id.in_(ids))
        )
        return {fila[0]: str(fila[1]) for fila in filas}

    # ------------------------------------------------------------- ocupación

    async def occupancy(
        self, desde: date, hasta: date, group_by: Literal["professional", "chair"]
    ) -> OccupancyReport:
        w = await self.window(desde, hasta)
        final = self._final(w)
        grupo = final.c.professional_id if group_by == "professional" else final.c.chair_id
        vigente = final.c.status.in_(VIGENT_STATUSES)
        normal = and_(vigente, not_(final.c.is_overbooking))
        minutos = extract("epoch", final.c.slot_ends_at - final.c.slot_starts_at) / 60
        filas = await self.session.execute(
            select(
                grupo.label("resource_id"),
                func.count().filter(normal).label("appointments"),
                func.count().filter(and_(vigente, final.c.is_overbooking)).label("overbookings"),
                func.coalesce(func.sum(minutos).filter(normal), 0).label("booked_min"),
            ).group_by(grupo)
        )
        reservado = {
            f.resource_id: (int(f.appointments), int(f.overbookings), round(f.booked_min))
            for f in filas
        }

        por_profesional, por_sillon = await self._capacity(w)
        capacidad = por_profesional if group_by == "professional" else por_sillon

        ids = set(reservado) | set(capacidad)
        nombres = await self._names(Professional if group_by == "professional" else Chair, ids)
        rows: list[OccupancyRow] = []
        for rid in sorted(ids, key=lambda i: (nombres.get(i, ""), str(i))):
            turnos, sobreturnos, reservados = reservado.get(rid, (0, 0, 0))
            cap = capacidad.get(rid, 0)
            rows.append(
                OccupancyRow(
                    resource_id=rid,
                    resource_name=nombres.get(rid, ""),
                    appointments=turnos,
                    overbookings=sobreturnos,
                    booked_min=reservados,
                    capacity_min=cap,
                    occupancy_pct=_pct(reservados, cap),
                )
            )
        total_res = sum(r.booked_min for r in rows)
        total_cap = sum(r.capacity_min for r in rows)
        return OccupancyReport(
            group_by=group_by,
            from_date=desde,
            to_date=hasta,
            rows=rows,
            totals=OccupancyTotals(
                appointments=sum(r.appointments for r in rows),
                overbookings=sum(r.overbookings for r in rows),
                booked_min=total_res,
                capacity_min=total_cap,
                occupancy_pct=_pct(total_res, total_cap),
            ),
        )

    async def _capacity(self, w: ReportWindow) -> tuple[dict[uuid.UUID, int], dict[uuid.UUID, int]]:
        reglas = (
            await self.session.execute(
                select(ScheduleRule).where(
                    ScheduleRule.clinic_id == self.clinic_id,
                    ScheduleRule.active.is_(True),
                    ScheduleRule.valid_from <= w.last_day,
                    or_(ScheduleRule.valid_to.is_(None), ScheduleRule.valid_to >= w.first_day),
                )
            )
        ).scalars()
        bloqueos = (
            await self.session.execute(
                select(Block.professional_id, Block.chair_id, Block.starts_at, Block.ends_at).where(
                    Block.clinic_id == self.clinic_id,
                    Block.removed_at.is_(None),
                    Block.starts_at < w.end_at,
                    Block.ends_at > w.start_at,
                )
            )
        ).all()
        return capacity_minutes(
            [
                RuleCapacity(
                    r.professional_id,
                    r.chair_id,
                    RuleWindow(
                        weekday=r.weekday,
                        start_time=r.start_time,
                        end_time=r.end_time,
                        slot_duration_min=r.slot_duration_min,
                        valid_from=r.valid_from,
                        valid_to=r.valid_to,
                    ),
                )
                for r in reglas
            ],
            [BlockSpan(b[0], b[1], b[2], b[3]) for b in bloqueos],
            w.first_day,
            w.last_day,
            w.tz,
        )

    # ------------------------------------------------------------ ausentismo

    async def absenteeism(self, desde: date, hasta: date) -> AbsenteeismReport:
        w = await self.window(desde, hasta)
        final = self._final(w)
        estado = final.c.status
        conteos = await self.session.execute(
            select(
                final.c.professional_id,
                func.count().filter(estado == AppointmentStatus.PRESENT).label("present"),
                func.count().filter(estado == AppointmentStatus.ABSENT).label("absent"),
                func.count().filter(estado == AppointmentStatus.NO_SHOW).label("no_show"),
            ).group_by(final.c.professional_id)
        )
        datos: dict[uuid.UUID, list[int]] = {
            f.professional_id: [int(f.present), int(f.absent), int(f.no_show), 0] for f in conteos
        }
        cancelacion = self._cancel_events(final)
        tardias = await self.session.execute(
            select(final.c.professional_id, func.count())
            .join_from(final, cancelacion, cancelacion.c.appointment_id == final.c.appointment_id)
            .where(estado == AppointmentStatus.CANCELLED, cancelacion.c.late.is_(True))
            .group_by(final.c.professional_id)
        )
        for profesional_id, cantidad in tardias:
            datos.setdefault(profesional_id, [0, 0, 0, 0])[3] = int(cantidad)

        nombres = await self._names(Professional, set(datos))
        rows: list[AbsenteeismRow] = []
        for pid in sorted(datos, key=lambda i: (nombres.get(i, ""), str(i))):
            presentes, ausentes, no_show, tardias_n = datos[pid]
            resultados = presentes + ausentes + no_show + tardias_n
            rows.append(
                AbsenteeismRow(
                    professional_id=pid,
                    professional_name=nombres.get(pid, ""),
                    present=presentes,
                    absent=ausentes,
                    no_show=no_show,
                    late_cancellations=tardias_n,
                    outcomes=resultados,
                    no_show_rate=_rate(no_show, resultados),
                    absent_rate=_rate(ausentes, resultados),
                    late_cancellation_rate=_rate(tardias_n, resultados),
                )
            )
        t_pres, t_aus = sum(r.present for r in rows), sum(r.absent for r in rows)
        t_ns, t_tar = sum(r.no_show for r in rows), sum(r.late_cancellations for r in rows)
        t_res = t_pres + t_aus + t_ns + t_tar
        return AbsenteeismReport(
            from_date=desde,
            to_date=hasta,
            rows=rows,
            totals=AbsenteeismTotals(
                present=t_pres,
                absent=t_aus,
                no_show=t_ns,
                late_cancellations=t_tar,
                outcomes=t_res,
                no_show_rate=_rate(t_ns, t_res),
                absent_rate=_rate(t_aus, t_res),
                late_cancellation_rate=_rate(t_tar, t_res),
            ),
        )

    # --------------------------------------------------------- cancelaciones

    async def cancellations(self, desde: date, hasta: date) -> CancellationsReport:
        w = await self.window(desde, hasta)
        final = self._final(w)
        cancelacion = self._cancel_events(final)
        filas = await self.session.execute(
            select(
                cancelacion.c.reason,
                func.count().label("total"),
                func.count().filter(cancelacion.c.late.is_(True)).label("late"),
            )
            .join_from(final, cancelacion, cancelacion.c.appointment_id == final.c.appointment_id)
            .where(final.c.status == AppointmentStatus.CANCELLED)
            .group_by(cancelacion.c.reason)
        )
        por_motivo = {m.value: [0, 0] for m in CancellationReason}
        for motivo, total, tardias in filas:
            # Sin motivo (cancelación del paciente por token, C-08) cuenta como `otro`.
            clave = motivo if motivo in por_motivo else CancellationReason.OTRO.value
            por_motivo[clave][0] += int(total)
            por_motivo[clave][1] += int(tardias)
        rows = [
            CancellationRow(reason=m, total=t, late=late, in_window=t - late)
            for m, (t, late) in por_motivo.items()
        ]
        return CancellationsReport(
            from_date=desde, to_date=hasta, rows=rows, total=sum(r.total for r in rows)
        )
