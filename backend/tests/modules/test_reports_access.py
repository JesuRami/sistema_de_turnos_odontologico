"""RBAC, rango y aislamiento de los reportes y la auditoría de clínica (C-13, S1/S2)."""

from __future__ import annotations

import httpx
import pytest
from app.core.settings import Settings
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tests.appointment_helpers import make_agenda
from tests.conftest import MutableClock
from tests.report_helpers import DIA, alta, rango, reporte

pytestmark = pytest.mark.integration

RUTAS = [
    ("/api/reports/occupancy", rango()),
    ("/api/reports/absenteeism", rango()),
    ("/api/reports/cancellations", rango()),
    ("/api/audit/appointments", {}),
    ("/api/exports/full", {"format": "csv"}),
]


@pytest.mark.parametrize(("ruta", "params"), RUTAS)
async def test_admin_accede_y_los_demas_roles_no(
    ruta: str,
    params: dict[str, str],
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)

    admin = await app_client.get(ruta, params=params, headers=agenda.headers["admin"])
    recepcion = await app_client.get(ruta, params=params, headers=agenda.headers["recepcion"])
    odontologo = await app_client.get(ruta, params=params, headers=agenda.headers["odontologo"])
    anonimo = await app_client.get(ruta, params=params)

    assert admin.status_code == 200, admin.text
    assert recepcion.status_code == 403
    assert recepcion.json() == {"detail": "forbidden_role"}
    assert odontologo.status_code == 403
    assert anonimo.status_code == 401


async def test_rango_invertido_y_excesivo_se_rechazan(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)

    invertido = await app_client.get(
        "/api/reports/occupancy",
        params={"from": "2030-01-21", "to": "2030-01-14"},
        headers=agenda.headers["admin"],
    )
    excesivo = await app_client.get(
        "/api/reports/occupancy",
        params={"from": "2030-01-01", "to": "2031-01-02"},
        headers=agenda.headers["admin"],
    )
    limite = await app_client.get(
        "/api/reports/occupancy",
        params={"from": "2030-01-01", "to": "2030-12-31"},
        headers=agenda.headers["admin"],
    )

    assert (invertido.status_code, invertido.json()) == (422, {"detail": "invalid_range"})
    assert (excesivo.status_code, excesivo.json()) == (422, {"detail": "range_too_large"})
    assert limite.status_code == 200


async def test_parametro_desconocido_y_formato_invalido_se_rechazan(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)

    extra = await reporte(app_client, agenda, "absenteeism", clinic_id="otra")
    formato = await reporte(app_client, agenda, "absenteeism", format="xml")

    assert (extra.status_code, extra.json()) == (422, {"detail": "unknown_parameter"})
    assert (formato.status_code, formato.json()) == (422, {"detail": "invalid_format"})


async def test_cada_clinica_ve_solo_sus_turnos(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    clinica_a = await make_agenda(db_session, redis_client, settings)
    clinica_b = await make_agenda(db_session, redis_client, settings)
    await alta(app_client, clinica_a, 10)
    await alta(app_client, clinica_b, 10)
    await alta(app_client, clinica_b, 11)

    informe = (await reporte(app_client, clinica_a, "occupancy")).json()

    assert informe["totals"]["appointments"] == 1
    assert {fila["resource_id"] for fila in informe["rows"]} == {
        str(clinica_a.staff.professional.id)
    }
    assert DIA.isoformat() == informe["from_date"]
