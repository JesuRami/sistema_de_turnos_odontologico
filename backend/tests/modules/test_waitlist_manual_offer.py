"""Oferta manual, huecos ofrecibles y acciones de recepción sobre ofertas (C-12, D10/D11).

Spec `waitlist/offers`. Postgres y Redis reales; reloj de la app en `AGENDA_NOW` (lunes 07/01/2030
08:00 local). Regla de los miércoles 09:00–13:00 de 30 min. Datos ficticios (regla 13).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time, timedelta
from typing import Any

import httpx
import pytest
from app.core.settings import Settings
from app.models import (
    Patient,
    WaitingListEntry,
    WaitingListStatus,
    WaitlistEvent,
    WaitlistOffer,
    WaitlistOfferStatus,
)
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.agenda_helpers import Staff, make_staff
from tests.conftest import AGENDA_NOW, MutableClock
from tests.factories import make_appointment, make_patient, make_professional, make_schedule_rule
from tests.waitlist_helpers import URL, make_entry, make_offer

pytestmark = pytest.mark.integration

HUECO = AGENDA_NOW + timedelta(days=2, hours=2)  # miércoles 10:00 local


@dataclass
class Escena:
    staff: Staff
    entradas: list[WaitingListEntry]


async def _escena(
    db: AsyncSession, redis: Redis, settings: Settings, n: int = 3, **entrada: Any
) -> Escena:
    staff = await make_staff(db, redis, settings)
    await make_schedule_rule(
        db,
        staff.clinic,
        staff.professional,
        staff.chair,
        weekday=2,
        start_time=time(9),
        end_time=time(13),
    )
    entradas = []
    for i in range(n):
        paciente: Patient = await make_patient(
            db, staff.clinic, full_name=f"Espera Ficticia {i}", whatsapp_opt_in=True
        )
        valores: dict[str, Any] = {"date_from": date(2030, 1, 7), "date_to": date(2030, 1, 20)}
        valores.update(entrada)
        entry = await make_entry(db, staff.clinic, paciente, **valores)
        await db.execute(
            update(WaitingListEntry)
            .where(WaitingListEntry.id == entry.id)
            .values(created_at=AGENDA_NOW - timedelta(days=10 - i))
        )
        entradas.append(entry)
    return Escena(staff, entradas)


def _cuerpo(e: Escena, starts_at: Any = HUECO, **cambios: Any) -> dict[str, Any]:
    cuerpo: dict[str, Any] = {
        "professional_id": str(e.staff.professional.id),
        "chair_id": str(e.staff.chair.id),
        "starts_at": starts_at.isoformat(),
    }
    cuerpo.update(cambios)
    return cuerpo


async def _ofrecer(
    client: httpx.AsyncClient, e: Escena, entry: WaitingListEntry, rol: str = "recepcion", **kw: Any
) -> httpx.Response:
    return await client.post(
        f"{URL}/{entry.id}/offers", json=_cuerpo(e, **kw), headers=e.staff.headers[rol]
    )


async def test_huecos_respetan_la_preferencia(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(
        db_session, redis_client, settings, n=1, time_from=time(11), time_to=time(12, 30)
    )

    r = await app_client.get(
        f"{URL}/{e.entradas[0].id}/slots",
        params={"from": AGENDA_NOW.isoformat(), "to": (AGENDA_NOW + timedelta(days=7)).isoformat()},
        headers=e.staff.headers["recepcion"],
    )

    assert r.status_code == 200, r.text
    horas = [i["starts_at"] for i in r.json()["items"]]
    # Miércoles 09/01: 11:00, 11:30 y 12:00 local (14:00–15:00 UTC); 12:30 terminaría fuera.
    assert horas == [
        "2030-01-09T14:00:00Z",
        "2030-01-09T14:30:00Z",
        "2030-01-09T15:00:00Z",
    ]


async def test_huecos_para_cualquiera_incluyen_todos_los_profesionales(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, settings, n=1)
    otro = await make_professional(db_session, e.staff.clinic)
    from tests.factories import make_chair

    sillon = await make_chair(db_session, e.staff.clinic)
    await make_schedule_rule(db_session, e.staff.clinic, otro, sillon, weekday=2)

    r = await app_client.get(
        f"{URL}/{e.entradas[0].id}/slots",
        params={"from": AGENDA_NOW.isoformat(), "to": (AGENDA_NOW + timedelta(days=7)).isoformat()},
        headers=e.staff.headers["recepcion"],
    )

    profesionales = {i["professional_id"] for i in r.json()["items"]}
    assert profesionales == {str(e.staff.professional.id), str(otro.id)}


async def test_huecos_rango_excesivo(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, settings, n=1)

    r = await app_client.get(
        f"{URL}/{e.entradas[0].id}/slots",
        params={
            "from": AGENDA_NOW.isoformat(),
            "to": (AGENDA_NOW + timedelta(days=15)).isoformat(),
        },
        headers=e.staff.headers["recepcion"],
    )

    assert r.status_code == 422
    assert r.json()["detail"] == "range_too_large"


async def test_oferta_manual_a_la_primera_sin_motivo(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, settings)

    r = await _ofrecer(app_client, e, e.entradas[0])

    assert r.status_code == 201, r.text
    assert r.json()["status"] == "pending"
    assert r.json()["mode"] == "manual"
    assert r.json()["ends_at"] == "2030-01-09T13:30:00Z"


async def test_saltear_la_cola_exige_motivo(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, settings)

    sin = await _ofrecer(app_client, e, e.entradas[2])
    con = await _ofrecer(
        app_client, e, e.entradas[2], fifo_skip_reason="Paciente con urgencia por dolor"
    )

    assert sin.status_code == 422
    assert sin.json()["detail"] == "fifo_skip_reason_required"
    assert con.status_code == 201, con.text
    evento = await db_session.scalar(
        select(WaitlistEvent).where(WaitlistEvent.offer_id == con.json()["id"])
    )
    assert evento is not None
    assert evento.payload["fifo_skip"] is True
    assert evento.payload["fifo_skip_reason"] == "Paciente con urgencia por dolor"
    assert evento.actor_user_id is not None


async def test_hueco_ocupado(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, settings)
    titular = await make_patient(db_session, e.staff.clinic)
    await make_appointment(
        db_session,
        e.staff.clinic,
        patient=titular,
        professional=e.staff.professional,
        chair=e.staff.chair,
        starts_at=HUECO,
    )

    r = await _ofrecer(app_client, e, e.entradas[0])

    assert r.status_code == 409
    assert r.json()["detail"] == "slot_taken"


async def test_fuera_de_horario(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, settings)

    r = await _ofrecer(app_client, e, e.entradas[0], starts_at=HUECO + timedelta(hours=5))

    assert r.status_code == 422
    assert r.json()["detail"] == "outside_schedule"


async def test_segunda_oferta_a_la_misma_entrada(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, settings)
    await _ofrecer(app_client, e, e.entradas[0])

    r = await _ofrecer(app_client, e, e.entradas[0], starts_at=HUECO + timedelta(minutes=30))

    assert r.status_code == 409
    assert r.json()["detail"] == "entry_offered"


async def test_rechazar_y_retirar_en_nombre_del_paciente(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, settings, n=2)
    primera = (await _ofrecer(app_client, e, e.entradas[0])).json()

    r = await app_client.post(
        f"{URL}/offers/{primera['id']}/decline", headers=e.staff.headers["recepcion"]
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "declined"
    # El hueco rota a la segunda entrada; recepción la retira.
    rotada = await db_session.scalar(
        select(WaitlistOffer).where(
            WaitlistOffer.entry_id == e.entradas[1].id,
            WaitlistOffer.status == WaitlistOfferStatus.PENDING,
        )
    )
    assert rotada is not None
    r = await app_client.post(
        f"{URL}/offers/{rotada.id}/cancel", headers=e.staff.headers["recepcion"]
    )

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled"
    assert r.json()["closed_reason"] == "withdrawn_by_staff"
    eventos = list(
        (
            await db_session.execute(
                select(WaitlistEvent).where(WaitlistEvent.offer_id == rotada.id)
            )
        ).scalars()
    )
    assert {ev.event.value for ev in eventos} == {"offer_created", "offer_cancelled"}
    cancelado = next(ev for ev in eventos if ev.event.value == "offer_cancelled")
    assert cancelado.actor_user_id is not None


async def test_listado_de_ofertas_por_estado(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, settings, n=2)
    await make_offer(
        db_session,
        e.entradas[0],
        professional=e.staff.professional,
        chair=e.staff.chair,
        starts_at=HUECO,
        now=AGENDA_NOW - timedelta(hours=5),
        expires_in=timedelta(hours=1),
        status=WaitlistOfferStatus.EXPIRED,
    )
    pendiente = (await _ofrecer(app_client, e, e.entradas[1])).json()

    vencidas = await app_client.get(
        f"{URL}/offers", params={"status": "expired"}, headers=e.staff.headers["recepcion"]
    )
    pendientes = await app_client.get(
        f"{URL}/offers", params={"status": "pending"}, headers=e.staff.headers["recepcion"]
    )

    assert [o["entry_id"] for o in vencidas.json()["items"]] == [str(e.entradas[0].id)]
    assert [o["id"] for o in pendientes.json()["items"]] == [pendiente["id"]]


@pytest.mark.parametrize(
    ("metodo", "ruta"),
    [
        ("GET", "/offers"),
        ("POST", "/offers/{oferta}/accept"),
        ("POST", "/offers/{oferta}/decline"),
        ("POST", "/offers/{oferta}/cancel"),
        ("POST", "/{entrada}/offers"),
        ("GET", "/{entrada}/slots"),
    ],
)
async def test_odontologo_sin_acciones_sobre_ofertas(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
    metodo: str,
    ruta: str,
) -> None:
    e = await _escena(db_session, redis_client, settings, n=1, status=WaitingListStatus.OFFERED)
    oferta = await make_offer(
        db_session,
        e.entradas[0],
        professional=e.staff.professional,
        chair=e.staff.chair,
        starts_at=HUECO,
        now=AGENDA_NOW,
    )

    r = await app_client.request(
        metodo,
        URL + ruta.format(oferta=oferta.id, entrada=e.entradas[0].id),
        json=_cuerpo(e) if ruta.endswith("/offers") and metodo == "POST" else None,
        params=(
            {"from": AGENDA_NOW.isoformat(), "to": HUECO.isoformat()}
            if ruta.endswith("slots")
            else None
        ),
        headers=e.staff.headers["odontologo"],
    )

    assert r.status_code == 403
