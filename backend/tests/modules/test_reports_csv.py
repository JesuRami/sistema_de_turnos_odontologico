"""CSV de reportes: mismas cifras que el JSON, encabezados fijos y sin fórmulas (C-13, S1)."""

from __future__ import annotations

import csv
import io

import httpx
import pytest
from app.core.settings import Settings
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.appointment_helpers import make_agenda
from tests.conftest import MutableClock
from tests.report_helpers import alta, reporte

pytestmark = pytest.mark.integration


def _filas(respuesta: httpx.Response) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(respuesta.content.decode("utf-8-sig"))))


async def test_csv_de_ocupacion_coincide_con_el_json(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    await alta(app_client, agenda, 10, duration=60)

    en_json = (await reporte(app_client, agenda, "occupancy")).json()["rows"][0]
    en_csv = await reporte(app_client, agenda, "occupancy", format="csv")

    assert en_csv.headers["content-type"].startswith("text/csv")
    assert "attachment" in en_csv.headers["content-disposition"]
    fila = _filas(en_csv)[0]
    assert list(fila) == [
        "resource_id",
        "resource_name",
        "appointments",
        "overbookings",
        "booked_min",
        "capacity_min",
        "occupancy_pct",
    ]
    assert fila["resource_id"] == en_json["resource_id"]
    assert int(fila["booked_min"]) == en_json["booked_min"] == 60
    assert float(fila["occupancy_pct"]) == en_json["occupancy_pct"]


async def test_csv_neutraliza_celdas_que_parecen_formulas(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    await alta(app_client, agenda, 10)
    await db_session.execute(
        text("UPDATE professional SET display_name = '=SUMA(A1:A2)' WHERE id = :id"),
        {"id": agenda.staff.professional.id},
    )

    respuesta = await reporte(app_client, agenda, "occupancy", format="csv")

    assert _filas(respuesta)[0]["resource_name"] == "'=SUMA(A1:A2)"


async def test_csv_de_ausentismo_y_cancelaciones_tienen_encabezados_fijos(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await alta(app_client, agenda, 10)
    await app_client.post(
        f"/api/appointments/{turno}/transitions",
        json={"to": "cancelled", "reason": "paciente"},
        headers=agenda.headers["recepcion"],
    )

    cancelaciones = await reporte(app_client, agenda, "cancellations", format="csv")
    ausentismo = await reporte(app_client, agenda, "absenteeism", format="csv")

    assert _filas(cancelaciones)[0].keys() == {"reason", "total", "late", "in_window"}
    assert len(_filas(cancelaciones)) == 5
    assert ausentismo.status_code == 200
    assert "no_show_rate" in ausentismo.content.decode("utf-8-sig").splitlines()[0]
