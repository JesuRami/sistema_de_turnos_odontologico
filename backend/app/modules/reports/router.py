"""Router de reportes, auditoría de clínica y exportación (C-13). Solo admin.

Routers finos → `ReportsService`, `list_audit` y `ExportService`. El `clinic_id`
sale siempre del `Principal`, nunca de la request (regla 4). Los parámetros de
query desconocidos se rechazan (regla 2).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import AwareDatetime
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.clock import get_now
from app.common.csv_export import csv_response
from app.common.dependencies import require_roles
from app.common.exceptions import DomainError
from app.common.principal import Principal
from app.core.deps import get_db
from app.models import AppointmentEventType, UserRole
from app.modules.reports.audit_feed import list_audit
from app.modules.reports.exports import ExportFormat, ExportService, iter_file
from app.modules.reports.schemas import (
    AbsenteeismReport,
    AuditPage,
    CancellationsReport,
    OccupancyReport,
    WaitlistReport,
    WhatsAppReport,
)
from app.modules.reports.service import ReportsService
from app.modules.reports.waitlist import waitlist_report
from app.modules.reports.whatsapp import whatsapp_report

router = APIRouter(prefix="/api", tags=["reports"])

DbSession = Annotated[AsyncSession, Depends(get_db)]
Now = Annotated[datetime, Depends(get_now)]
AdminDep = Annotated[Principal, Depends(require_roles(UserRole.ADMIN))]

Desde = Annotated[date, Query(alias="from")]
Hasta = Annotated[date, Query(alias="to")]
Formato = Annotated[str, Query(alias="format")]


def only_params(*allowed: str) -> Callable[[Request], Awaitable[None]]:
    """Dependencia que rechaza parámetros de query no declarados (`422`)."""
    permitidos = set(allowed)

    async def _check(request: Request) -> None:
        if set(request.query_params) - permitidos:
            raise DomainError(422, "unknown_parameter")

    return _check


def _format(value: str) -> Literal["json", "csv"]:
    if value not in ("json", "csv"):
        raise DomainError(422, "invalid_format")
    return value  # type: ignore[return-value]


@router.get(
    "/reports/occupancy",
    response_model=OccupancyReport,
    dependencies=[Depends(only_params("from", "to", "group_by", "format"))],
)
async def occupancy(
    principal: AdminDep,
    session: DbSession,
    desde: Desde,
    hasta: Hasta,
    group_by: Annotated[Literal["professional", "chair"], Query()] = "professional",
    formato: Annotated[str, Query(alias="format")] = "json",
) -> OccupancyReport | Response:
    """Ocupación por profesional o sillón: minutos reservados sobre capacidad."""
    fmt = _format(formato)
    informe = await ReportsService(session, principal.clinic_id).occupancy(desde, hasta, group_by)
    if fmt == "csv":
        return csv_response(
            f"ocupacion-{group_by}-{desde}-{hasta}.csv",
            [
                "resource_id",
                "resource_name",
                "appointments",
                "overbookings",
                "booked_min",
                "capacity_min",
                "occupancy_pct",
            ],
            [
                [
                    r.resource_id,
                    r.resource_name,
                    r.appointments,
                    r.overbookings,
                    r.booked_min,
                    r.capacity_min,
                    r.occupancy_pct,
                ]
                for r in informe.rows
            ],
        )
    return informe


@router.get(
    "/reports/absenteeism",
    response_model=AbsenteeismReport,
    dependencies=[Depends(only_params("from", "to", "format"))],
)
async def absenteeism(
    principal: AdminDep,
    session: DbSession,
    desde: Desde,
    hasta: Hasta,
    formato: Annotated[str, Query(alias="format")] = "json",
) -> AbsenteeismReport | Response:
    """Ausentismo: `no_show`, `absent` y cancelación tardía por separado (RN-ST-04)."""
    fmt = _format(formato)
    informe = await ReportsService(session, principal.clinic_id).absenteeism(desde, hasta)
    if fmt == "csv":
        return csv_response(
            f"ausentismo-{desde}-{hasta}.csv",
            [
                "professional_id",
                "professional_name",
                "present",
                "absent",
                "no_show",
                "late_cancellations",
                "outcomes",
                "no_show_rate",
                "absent_rate",
                "late_cancellation_rate",
            ],
            [
                [
                    r.professional_id,
                    r.professional_name,
                    r.present,
                    r.absent,
                    r.no_show,
                    r.late_cancellations,
                    r.outcomes,
                    r.no_show_rate,
                    r.absent_rate,
                    r.late_cancellation_rate,
                ]
                for r in informe.rows
            ],
        )
    return informe


@router.get(
    "/reports/whatsapp",
    response_model=WhatsAppReport,
    dependencies=[Depends(only_params("from", "to", "format"))],
)
async def whatsapp(
    principal: AdminDep,
    session: DbSession,
    desde: Desde,
    hasta: Hasta,
    formato: Annotated[str, Query(alias="format")] = "json",
) -> WhatsAppReport | Response:
    """Mensajes enviados/entregados/leídos/fallidos y costo por paso y canal (C-10, RN-WA-05)."""
    fmt = _format(formato)
    ventana = await ReportsService(session, principal.clinic_id).window(desde, hasta)
    informe = await whatsapp_report(session, principal.clinic_id, ventana)
    if fmt == "csv":
        t = informe.totals
        return csv_response(
            f"whatsapp-{desde}-{hasta}.csv",
            ["step", "channel", "sent", "delivered", "read", "failed", "cost_usd"],
            [
                [r.step, r.channel, r.sent, r.delivered, r.read, r.failed, r.cost_usd]
                for r in informe.rows
            ]
            + [["total", "", t.sent, t.delivered, t.read, t.failed, t.cost_usd]],
        )
    return informe


@router.get(
    "/reports/waitlist",
    response_model=WaitlistReport,
    dependencies=[Depends(only_params("from", "to", "format"))],
)
async def waitlist(
    principal: AdminDep,
    session: DbSession,
    desde: Desde,
    hasta: Hasta,
    formato: Annotated[str, Query(alias="format")] = "json",
) -> WaitlistReport | Response:
    """Conversión de la lista de espera por profesional (C-12, US-050), sobre `waitlist_event`."""
    fmt = _format(formato)
    ventana = await ReportsService(session, principal.clinic_id).window(desde, hasta)
    informe = await waitlist_report(session, principal.clinic_id, ventana)
    if fmt == "csv":
        columnas = [
            "created",
            "auto",
            "manual",
            "accepted",
            "declined",
            "expired",
            "cancelled",
            "conversion_pct",
        ]
        t = informe.totals
        return csv_response(
            f"lista-de-espera-{desde}-{hasta}.csv",
            ["professional_id", "professional_name", *columnas],
            [
                [r.professional_id, r.professional_name, *(getattr(r, c) for c in columnas)]
                for r in informe.rows
            ]
            + [["total", "", *(getattr(t, c) for c in columnas)]],
        )
    return informe


@router.get(
    "/reports/cancellations",
    response_model=CancellationsReport,
    dependencies=[Depends(only_params("from", "to", "format"))],
)
async def cancellations(
    principal: AdminDep,
    session: DbSession,
    desde: Desde,
    hasta: Hasta,
    formato: Annotated[str, Query(alias="format")] = "json",
) -> CancellationsReport | Response:
    """Cancelaciones por motivo del catálogo (RN-CX-04), con corte tardía / en ventana."""
    fmt = _format(formato)
    informe = await ReportsService(session, principal.clinic_id).cancellations(desde, hasta)
    if fmt == "csv":
        return csv_response(
            f"cancelaciones-{desde}-{hasta}.csv",
            ["reason", "total", "late", "in_window"],
            [[r.reason, r.total, r.late, r.in_window] for r in informe.rows],
        )
    return informe


@router.get(
    "/audit/appointments",
    response_model=AuditPage,
    dependencies=[
        Depends(
            only_params("appointment_id", "actor_user_id", "event", "from", "to", "cursor", "limit")
        )
    ],
)
async def audit_appointments(
    principal: AdminDep,
    session: DbSession,
    appointment_id: Annotated[uuid.UUID | None, Query()] = None,
    actor_user_id: Annotated[uuid.UUID | None, Query()] = None,
    event: Annotated[AppointmentEventType | None, Query()] = None,
    desde: Annotated[AwareDatetime | None, Query(alias="from")] = None,
    hasta: Annotated[AwareDatetime | None, Query(alias="to")] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AuditPage:
    """Eventos de turnos de la clínica, del más antiguo al más nuevo, con cursor."""
    return await list_audit(
        session,
        principal.clinic_id,
        appointment_id=appointment_id,
        actor_user_id=actor_user_id,
        event=event,
        desde=desde,
        hasta=hasta,
        cursor=cursor,
        limit=limit,
    )


@router.get(
    "/exports/full",
    dependencies=[Depends(only_params("format"))],
    response_class=StreamingResponse,
)
async def export_full(
    principal: AdminDep,
    session: DbSession,
    now: Now,
    formato: Formato = "csv",
) -> StreamingResponse:
    """ZIP con turnos, pacientes operativos y eventos (CSV o JSON). Queda auditado."""
    fmt: ExportFormat = "csv" if formato == "csv" else "json"
    if formato not in ("csv", "json"):
        raise DomainError(422, "invalid_format")
    servicio = ExportService(session, principal.clinic_id, principal.user_id)
    archivo, tamano, conteos = await servicio.build(fmt)
    try:
        await servicio.audit(fmt, conteos)
    except BaseException:
        archivo.close()
        raise
    return StreamingResponse(
        iter_file(archivo),
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="export-completo-{now.date().isoformat()}.zip"'
            ),
            "Content-Length": str(tamano),
        },
    )
