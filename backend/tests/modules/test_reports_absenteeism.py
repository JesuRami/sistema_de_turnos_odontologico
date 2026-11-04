"""Reporte de ausentismo: no_show, ausente y cancelación tardía por separado (C-13, RN-ST-04)."""

from __future__ import annotations

import httpx
import pytest
from app.core.settings import Settings
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tests.appointment_helpers import at, make_agenda
from tests.conftest import MutableClock
from tests.report_helpers import DIA, DIA2, alta, fijar_reloj, rango, reporte, transicion

pytestmark = pytest.mark.integration


async def test_no_show_y_cancelacion_tardia_se_cuentan_por_separado(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    tardia = await alta(app_client, agenda, 9)
    ausente = await alta(app_client, agenda, 10)
    fijar_reloj(agenda_clock, at(8, 0, days=7))
    await transicion(app_client, agenda, tardia, "cancelled", reason="paciente")
    fijar_reloj(agenda_clock, at(14, 0, days=7))
    await transicion(app_client, agenda, ausente, "no_show")

    totals = (await reporte(app_client, agenda, "absenteeism")).json()["totals"]

    assert (totals["no_show"], totals["late_cancellations"], totals["absent"]) == (1, 1, 0)


async def test_las_tasas_usan_present_absent_no_show_y_tardias_como_base(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    horarios = [(9, 0, 7), (9, 30, 7), (10, 0, 7), (10, 30, 7), (11, 0, 7)]
    horarios += [(11, 30, 7), (12, 0, 7), (12, 30, 7), (9, 0, 14), (9, 30, 14)]
    ids = [await alta(app_client, agenda, h, m, days=d) for h, m, d in horarios]

    fijar_reloj(agenda_clock, at(8, 0, days=7))
    await transicion(app_client, agenda, ids[0], "cancelled", reason="paciente")  # tardía
    fijar_reloj(agenda_clock, at(18, 0, days=14))
    for turno in ids[1:7]:
        await transicion(app_client, agenda, turno, "present")
    await transicion(app_client, agenda, ids[7], "absent")
    await transicion(app_client, agenda, ids[8], "no_show")
    await transicion(app_client, agenda, ids[9], "no_show")

    response = await app_client.get(
        "/api/reports/absenteeism", params=rango(DIA, DIA2), headers=agenda.headers["admin"]
    )

    totals = response.json()["totals"]
    assert (totals["present"], totals["absent"], totals["no_show"]) == (6, 1, 2)
    assert (totals["late_cancellations"], totals["outcomes"]) == (1, 10)
    assert totals["no_show_rate"] == 0.2
    assert (totals["absent_rate"], totals["late_cancellation_rate"]) == (0.1, 0.1)
    assert response.json()["rows"][0]["professional_id"] == str(agenda.staff.professional.id)


async def test_la_cancelacion_en_ventana_no_entra_en_el_denominador(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await alta(app_client, agenda, 10)
    await transicion(app_client, agenda, turno, "cancelled", reason="paciente")

    totals = (await reporte(app_client, agenda, "absenteeism")).json()["totals"]

    assert (totals["outcomes"], totals["late_cancellations"], totals["no_show_rate"]) == (0, 0, 0.0)
    assert DIA.isoformat() == rango()["from"]
