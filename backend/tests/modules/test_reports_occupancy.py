"""Reporte de ocupación: minutos reservados sobre capacidad (C-13, US-050 CA-1)."""

from __future__ import annotations

from datetime import time

import httpx
import pytest
from app.core.settings import Settings
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.appointment_helpers import Agenda, at, make_agenda
from tests.conftest import MutableClock
from tests.factories import make_block
from tests.report_helpers import alta, rango, reporte, transicion

pytestmark = pytest.mark.integration


async def _jornada(db_session: AsyncSession, redis_client: Redis, settings: Settings) -> Agenda:
    """Plantilla de 8 h (09:00-17:00) los lunes."""
    return await make_agenda(db_session, redis_client, settings, end_time=time(17, 0))


async def test_ocupacion_parcial_por_profesional(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await _jornada(db_session, redis_client, settings)
    await alta(app_client, agenda, 10, duration=60)
    await alta(app_client, agenda, 12, duration=60)

    informe = (await reporte(app_client, agenda, "occupancy")).json()

    fila = informe["rows"][0]
    assert fila["resource_id"] == str(agenda.staff.professional.id)
    assert (fila["booked_min"], fila["capacity_min"], fila["occupancy_pct"]) == (120, 480, 25.0)
    assert informe["capacity_basis"] == "current_schedule"
    assert informe["totals"]["occupancy_pct"] == 25.0


async def test_un_turno_cancelado_no_ocupa(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await _jornada(db_session, redis_client, settings)
    await alta(app_client, agenda, 10, duration=60)
    cancelado = await alta(app_client, agenda, 12, duration=60)
    await transicion(app_client, agenda, cancelado, "cancelled", reason="paciente")

    fila = (await reporte(app_client, agenda, "occupancy")).json()["rows"][0]

    assert (fila["appointments"], fila["booked_min"]) == (1, 60)


async def test_un_bloqueo_reduce_la_capacidad(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await _jornada(db_session, redis_client, settings)
    await make_block(
        db_session,
        agenda.staff.clinic,
        professional=agenda.staff.professional,
        starts_at=at(11, days=7),
        ends_at=at(13, days=7),
    )

    fila = (await reporte(app_client, agenda, "occupancy")).json()["rows"][0]

    assert fila["capacity_min"] == 360


async def test_sin_plantilla_la_ocupacion_es_cero_sin_error(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await _jornada(db_session, redis_client, settings)
    await alta(app_client, agenda, 10, duration=60)
    await db_session.execute(text("UPDATE schedule_rule SET active = false"))

    response = await reporte(app_client, agenda, "occupancy")

    assert response.status_code == 200
    fila = response.json()["rows"][0]
    assert (fila["booked_min"], fila["capacity_min"], fila["occupancy_pct"]) == (60, 0, 0.0)


async def test_el_sobreturno_se_cuenta_aparte_y_no_suma_minutos(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await _jornada(db_session, redis_client, settings)
    await alta(app_client, agenda, 10, duration=60)
    await alta(
        app_client,
        agenda,
        10,
        duration=60,
        rol="admin",
        is_overbooking=True,
        overbooking_reason="Urgencia ficticia",
    )

    fila = (await reporte(app_client, agenda, "occupancy")).json()["rows"][0]

    assert (fila["appointments"], fila["overbookings"], fila["booked_min"]) == (1, 1, 60)


async def test_agrupa_por_sillon(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await _jornada(db_session, redis_client, settings)
    await alta(app_client, agenda, 10, duration=60)

    informe = (await reporte(app_client, agenda, "occupancy", group_by="chair")).json()

    assert informe["group_by"] == "chair"
    fila = informe["rows"][0]
    assert fila["resource_id"] == str(agenda.staff.chair.id)
    assert fila["resource_name"] == agenda.staff.chair.name
    assert rango()["from"] == informe["from_date"]
