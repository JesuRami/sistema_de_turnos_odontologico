"""Cola consultable de la lista de espera (C-12; spec waitlist/entries, D11).

Orden por prioridad y antigüedad, filtros, oferta embebida, paginación por cursor, alcance por rol y
aislamiento. Postgres y Redis reales. Datos ficticios (regla 13).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import httpx
import pytest
from app.core.settings import Settings
from app.models import WaitingListEntry, WaitingListStatus
from redis.asyncio import Redis
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.agenda_helpers import make_staff
from tests.conftest import AGENDA_NOW, MutableClock
from tests.factories import make_patient, make_professional
from tests.waitlist_helpers import URL, make_entry, make_offer

pytestmark = pytest.mark.integration


async def _alta(db: AsyncSession, clinic: Any, minutos: int, **cambios: Any) -> WaitingListEntry:
    """Entrada con `created_at` fijo (antigüedad controlada)."""
    paciente = await make_patient(db, clinic)
    entry = await make_entry(db, clinic, paciente, **cambios)
    await db.execute(
        update(WaitingListEntry)
        .where(WaitingListEntry.id == entry.id)
        .values(created_at=AGENDA_NOW - timedelta(days=10) + timedelta(minutes=minutos))
    )
    return entry


def _ids(r: httpx.Response) -> list[str]:
    assert r.status_code == 200, r.text
    return [e["id"] for e in r.json()["items"]]


async def test_orden_prioridad_y_antiguedad(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    vieja = await _alta(db_session, staff.clinic, 1)
    nueva = await _alta(db_session, staff.clinic, 2)
    prioritaria = await _alta(
        db_session,
        staff.clinic,
        3,
        prioritized_at=AGENDA_NOW,
        priority_reason="Urgencia por dolor",
    )

    r = await app_client.get(URL, headers=staff.headers["recepcion"])

    assert _ids(r) == [str(prioritaria.id), str(vieja.id), str(nueva.id)]


async def test_filtro_por_profesional_incluye_cualquiera(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    otro = await make_professional(db_session, staff.clinic, display_name="Dra. Ficticia Dos")
    propia = await _alta(db_session, staff.clinic, 1, professional=staff.professional)
    cualquiera = await _alta(db_session, staff.clinic, 2)
    await _alta(db_session, staff.clinic, 3, professional=otro)

    r = await app_client.get(
        URL,
        params={"professional_id": str(staff.professional.id)},
        headers=staff.headers["recepcion"],
    )

    assert _ids(r) == [str(propia.id), str(cualquiera.id)]


async def test_filtro_por_periodo_por_interseccion(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    dentro = await _alta(
        db_session, staff.clinic, 1, date_from=date(2030, 1, 5), date_to=date(2030, 1, 10)
    )
    await _alta(db_session, staff.clinic, 2, date_from=date(2030, 1, 20), date_to=date(2030, 1, 25))

    r = await app_client.get(
        URL,
        params={"from": "2030-01-09", "to": "2030-01-15"},
        headers=staff.headers["recepcion"],
    )

    assert _ids(r) == [str(dentro.id)]


async def test_estado_por_defecto_y_filtro(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    esperando = await _alta(db_session, staff.clinic, 1)
    ofrecida = await _alta(db_session, staff.clinic, 2, status=WaitingListStatus.OFFERED)
    retirada = await _alta(
        db_session,
        staff.clinic,
        3,
        status=WaitingListStatus.WITHDRAWN,
        closed_reason="withdrawn_by_staff",
    )

    assert _ids(await app_client.get(URL, headers=staff.headers["recepcion"])) == [
        str(esperando.id),
        str(ofrecida.id),
    ]
    assert _ids(
        await app_client.get(
            URL, params={"status": "withdrawn"}, headers=staff.headers["recepcion"]
        )
    ) == [str(retirada.id)]


async def test_oferta_pendiente_embebida(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    entry = await _alta(db_session, staff.clinic, 1, status=WaitingListStatus.OFFERED)
    offer = await make_offer(
        db_session,
        entry,
        professional=staff.professional,
        chair=staff.chair,
        starts_at=AGENDA_NOW + timedelta(days=2),
        now=AGENDA_NOW,
    )

    r = await app_client.get(URL, headers=staff.headers["recepcion"])

    [item] = r.json()["items"]
    assert item["pending_offer"]["id"] == str(offer.id)
    assert item["pending_offer"]["mode"] == "auto"
    assert item["pending_offer"]["expires_at"] is not None


async def test_paginacion_estable(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    for i in range(7):
        extra: dict[str, Any] = (
            {"prioritized_at": AGENDA_NOW - timedelta(minutes=i), "priority_reason": "Urgencia x"}
            if i % 3 == 0
            else {}
        )
        await _alta(db_session, staff.clinic, i % 2, **extra)

    completa = _ids(
        await app_client.get(URL, params={"limit": 7}, headers=staff.headers["recepcion"])
    )
    paginas: list[str] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limit": 3, **({"cursor": cursor} if cursor else {})}
        r = await app_client.get(URL, params=params, headers=staff.headers["recepcion"])
        paginas += _ids(r)
        cursor = r.json()["next_cursor"]
        if cursor is None:
            break

    assert paginas == completa
    assert len(set(paginas)) == 7


async def test_odontologo_ve_lo_suyo_sin_contacto(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    otro = await make_professional(db_session, staff.clinic, display_name="Dra. Ficticia Dos")
    propia = await _alta(
        db_session, staff.clinic, 1, professional=staff.professional, notes="Nota interna"
    )
    cualquiera = await _alta(db_session, staff.clinic, 2)
    await _alta(db_session, staff.clinic, 3, professional=otro)

    r = await app_client.get(URL, headers=staff.headers["odontologo"])

    assert _ids(r) == [str(propia.id), str(cualquiera.id)]
    primera = r.json()["items"][0]
    assert set(primera["patient"]) == {"id", "full_name"}
    assert primera["notes"] is None


async def test_recepcion_ve_contacto(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    await _alta(db_session, staff.clinic, 1)

    r = await app_client.get(URL, headers=staff.headers["recepcion"])

    assert {"id", "full_name", "phone_e164", "email"} <= set(r.json()["items"][0]["patient"])


async def test_sin_sesion_y_aislamiento(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    a = await make_staff(db_session, redis_client, settings)
    b = await make_staff(db_session, redis_client, settings)
    await _alta(db_session, b.clinic, 1)

    assert (await app_client.get(URL)).status_code == 401
    assert _ids(await app_client.get(URL, headers=a.headers["admin"])) == []


@pytest.mark.parametrize("limite", [0, 201])
async def test_limite_fuera_de_rango(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
    limite: int,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)

    r = await app_client.get(URL, params={"limit": limite}, headers=staff.headers["recepcion"])

    assert r.status_code == 422
