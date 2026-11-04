"""Auditoría de turnos de la clínica: filtros, cursor, sin PII y solo admin (C-13, S2)."""

from __future__ import annotations

import httpx
import pytest
from app.core.settings import Settings
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tests.appointment_helpers import PACIENTE_NOMBRE, at, make_agenda
from tests.conftest import MutableClock
from tests.report_helpers import alta, fijar_reloj, transicion

pytestmark = pytest.mark.integration


async def _feed(client: httpx.AsyncClient, agenda: object, **params: object) -> httpx.Response:
    return await client.get(
        "/api/audit/appointments",
        params={k: str(v) for k, v in params.items()},
        headers=agenda.headers["admin"],  # type: ignore[attr-defined]
    )


async def test_filtra_por_turno_en_orden_cronologico(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    primero = await alta(app_client, agenda, 10)
    segundo = await alta(app_client, agenda, 11)
    await transicion(app_client, agenda, primero, "cancelled", reason="paciente")

    respuesta = await _feed(app_client, agenda, appointment_id=primero)

    items = respuesta.json()["items"]
    assert [i["event"] for i in items] == ["created", "cancelled"]
    assert {i["appointment_id"] for i in items} == {primero}
    assert segundo not in {i["appointment_id"] for i in items}


async def test_filtra_por_tipo_y_actor(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await alta(app_client, agenda, 10)
    await transicion(app_client, agenda, turno, "cancelled", reason="clinica")

    cancelados = (await _feed(app_client, agenda, event="cancelled")).json()["items"]
    de_otro = (await _feed(app_client, agenda, actor_user_id=agenda.staff.admin.id)).json()["items"]

    assert [i["event"] for i in cancelados] == ["cancelled"]
    assert cancelados[0]["from_status"] == "confirmed"
    assert cancelados[0]["to_status"] == "cancelled"
    assert de_otro == []


async def test_el_cursor_no_repite_ni_omite_filas(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    for hora in (9, 10, 11, 12):
        await alta(app_client, agenda, hora)

    vistos: list[str] = []
    cursor: str | None = None
    paginas = 0
    while True:
        params: dict[str, object] = {"limit": 3}
        if cursor:
            params["cursor"] = cursor
        pagina = (await _feed(app_client, agenda, **params)).json()
        vistos += [i["id"] for i in pagina["items"]]
        paginas += 1
        cursor = pagina["next_cursor"]
        if cursor is None:
            break

    assert len(vistos) == 4
    assert len(set(vistos)) == 4
    assert paginas == 2


async def test_no_expone_datos_del_paciente(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await alta(app_client, agenda, 10)
    fijar_reloj(agenda_clock, at(8, 30, days=7))
    await transicion(app_client, agenda, turno, "cancelled", reason="paciente")

    cuerpo = (await _feed(app_client, agenda)).text

    assert PACIENTE_NOMBRE not in cuerpo
    assert agenda.patient.phone_e164 not in cuerpo


async def test_no_mezcla_clinicas(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    clinica_a = await make_agenda(db_session, redis_client, settings)
    clinica_b = await make_agenda(db_session, redis_client, settings)
    turno_b = await alta(app_client, clinica_b, 10)

    items = (await _feed(app_client, clinica_a)).json()["items"]

    assert turno_b not in {i["appointment_id"] for i in items}
