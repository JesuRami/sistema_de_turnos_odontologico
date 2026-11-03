"""Aislamiento cross-tenant de turnos y pacientes (C-05 tarea 10.1, regla dura 4).

Un principal de la clínica B nunca lee, crea, modifica, transiciona ni ve
eventos de la clínica A: `404`/`422`, jamás datos.
"""

from __future__ import annotations

import httpx
import pytest
from app.core.settings import Settings
from app.models import AppointmentStatus
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tests.appointment_helpers import PACIENTE_NOMBRE, at, body, iso, make_agenda, reload, seed
from tests.conftest import MutableClock

pytestmark = pytest.mark.integration


async def test_admin_de_otra_clinica_no_ve_ni_toca_turnos(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    a = await make_agenda(db_session, redis_client, settings)
    b = await make_agenda(db_session, redis_client, settings)
    turno = await seed(db_session, a, at(10, days=7))
    intruso = b.headers["admin"]
    ruta = f"/api/appointments/{turno.id}"

    respuestas = [
        await app_client.get(ruta, headers=intruso),
        await app_client.patch(ruta, json={"starts_at": iso(11, days=7)}, headers=intruso),
        await app_client.patch(ruta, json={"notes": "Intrusa"}, headers=intruso),
        await app_client.post(
            f"{ruta}/transitions", json={"to": "cancelled", "reason": "otro"}, headers=intruso
        ),
        await app_client.get(f"{ruta}/events", headers=intruso),
    ]

    for response in respuestas:
        assert response.status_code == 404, response.text
        assert response.json() == {"detail": "not_found"}
    releido = await reload(db_session, turno.id)
    assert releido.status == AppointmentStatus.CONFIRMED
    assert releido.starts_at == at(10, days=7)
    assert releido.notes is None

    listado = await app_client.get(
        "/api/appointments",
        params={"from": iso(0), "to": iso(0, days=14)},
        headers=intruso,
    )
    assert listado.status_code == 200
    assert listado.json()["items"] == []


async def test_no_crea_turnos_con_referencias_de_otra_clinica(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    a = await make_agenda(db_session, redis_client, settings)
    b = await make_agenda(db_session, redis_client, settings)

    response = await app_client.post(
        "/api/appointments",
        json=body(b, at(10), patient_id=str(a.patient.id)),
        headers=b.headers["recepcion"],
    )
    reprogramar = await app_client.patch(
        f"/api/appointments/{(await seed(db_session, b, at(10))).id}",
        json={"chair_id": str(a.staff.chair.id)},
        headers=b.headers["recepcion"],
    )

    assert response.status_code == 422
    assert reprogramar.status_code == 422
    assert PACIENTE_NOMBRE not in response.text


async def test_busqueda_de_pacientes_no_cruza_clinicas(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    a = await make_agenda(db_session, redis_client, settings)
    b = await make_agenda(db_session, redis_client, settings)

    por_nombre = await app_client.get(
        "/api/patients", params={"q": PACIENTE_NOMBRE}, headers=b.headers["admin"]
    )
    por_telefono = await app_client.get(
        "/api/patients", params={"q": str(a.patient.phone_e164)}, headers=b.headers["admin"]
    )

    assert [p["id"] for p in por_nombre.json()["items"]] == [str(b.patient.id)]
    assert por_telefono.json()["items"] == []
