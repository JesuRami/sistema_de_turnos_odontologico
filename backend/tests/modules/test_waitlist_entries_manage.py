"""Edición, retiro y prioridad de entradas (C-12; spec waitlist/entries, D10).

Postgres y Redis reales; reloj de la app en `AGENDA_NOW`. Datos ficticios (regla 13).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import httpx
import pytest
from app.core.settings import Settings
from app.models import (
    ReminderChannel,
    ReminderJob,
    ReminderStatus,
    WaitingListEntry,
    WaitingListStatus,
    WaitlistEvent,
    WaitlistOffer,
    WaitlistOfferStatus,
)
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.agenda_helpers import Staff, make_staff
from tests.conftest import AGENDA_NOW, MutableClock
from tests.factories import make_patient
from tests.waitlist_helpers import URL, make_entry, make_offer

pytestmark = pytest.mark.integration

HUECO = AGENDA_NOW + timedelta(days=3)


async def _entrada(db: AsyncSession, staff: Staff, **cambios: object) -> WaitingListEntry:
    paciente = await make_patient(db, staff.clinic)
    return await make_entry(db, staff.clinic, paciente, **cambios)  # type: ignore[arg-type]


async def _eventos(db: AsyncSession, entry: WaitingListEntry) -> list[WaitlistEvent]:
    return list(
        (
            await db.execute(
                select(WaitlistEvent)
                .where(WaitlistEvent.entry_id == entry.id)
                .order_by(WaitlistEvent.created_at, WaitlistEvent.id)
            )
        ).scalars()
    )


async def _releer(db: AsyncSession, modelo: Any, id_: object) -> object:
    resultado: object = await db.scalar(
        select(modelo).where(modelo.id == id_).execution_options(populate_existing=True)
    )
    return resultado


async def test_editar_la_franja_registra_antes_y_despues(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    entry = await _entrada(db_session, staff)

    r = await app_client.patch(
        f"{URL}/{entry.id}",
        json={"time_from": "14:00", "time_to": "18:00", "notes": "Prefiere la tarde"},
        headers=staff.headers["recepcion"],
    )

    assert r.status_code == 200, r.text
    assert r.json()["time_to"] == "18:00:00"
    [evento] = await _eventos(db_session, entry)
    assert evento.event.value == "entry_updated"
    assert evento.payload["before"]["time_from"] is None
    assert evento.payload["after"]["time_from"] == "14:00:00"
    assert evento.payload["notes_changed"] is True
    assert "Prefiere" not in str(evento.payload)


async def test_editar_con_las_mismas_validaciones(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    entry = await _entrada(db_session, staff, date_from=AGENDA_NOW.date(), date_to=HUECO.date())

    r = await app_client.patch(
        f"{URL}/{entry.id}", json={"date_to": "2030-01-01"}, headers=staff.headers["recepcion"]
    )

    assert r.status_code == 422
    assert r.json()["detail"] == "invalid_range"


async def test_editar_una_ofrecida(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    entry = await _entrada(db_session, staff, status=WaitingListStatus.OFFERED)

    r = await app_client.patch(
        f"{URL}/{entry.id}", json={"notes": "otra"}, headers=staff.headers["recepcion"]
    )

    assert r.status_code == 409
    assert r.json()["detail"] == "entry_offered"


async def test_retiro_con_oferta_pendiente_cierra_oferta_y_envio(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    entry = await _entrada(db_session, staff, status=WaitingListStatus.OFFERED)
    offer = await make_offer(
        db_session,
        entry,
        professional=staff.professional,
        chair=staff.chair,
        starts_at=HUECO,
        now=AGENDA_NOW,
    )
    envio = ReminderJob(
        clinic_id=staff.clinic.id,
        waitlist_offer_id=offer.id,
        step="waitlist_offer",
        channel=ReminderChannel.WHATSAPP,
        scheduled_for=AGENDA_NOW,
        available_at=AGENDA_NOW,
        starts_at_snapshot=HUECO,
    )
    db_session.add(envio)
    await db_session.flush()

    r = await app_client.post(f"{URL}/{entry.id}/withdraw", headers=staff.headers["recepcion"])

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "withdrawn"
    oferta = await _releer(db_session, WaitlistOffer, offer.id)
    assert isinstance(oferta, WaitlistOffer)
    assert oferta.status is WaitlistOfferStatus.CANCELLED
    job = await _releer(db_session, ReminderJob, envio.id)
    assert isinstance(job, ReminderJob)
    assert job.status is ReminderStatus.CANCELLED
    assert job.reason == "offer_closed"
    tipos = [e.event.value for e in await _eventos(db_session, entry)]
    assert tipos == ["offer_cancelled", "entry_withdrawn"]


async def test_retirar_una_convertida(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    entry = await _entrada(
        db_session, staff, status=WaitingListStatus.CONVERTED, closed_reason="converted"
    )

    r = await app_client.post(f"{URL}/{entry.id}/withdraw", headers=staff.headers["recepcion"])

    assert r.status_code == 409
    assert r.json()["detail"] == "entry_closed"


async def test_priorizar_y_quitar_prioridad(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    entry = await _entrada(db_session, staff)

    r = await app_client.post(
        f"{URL}/{entry.id}/priority",
        json={"reason": "Urgencia por dolor"},
        headers=staff.headers["recepcion"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["priority_reason"] == "Urgencia por dolor"
    assert r.json()["prioritized_at"] is not None

    r = await app_client.delete(f"{URL}/{entry.id}/priority", headers=staff.headers["recepcion"])
    assert r.status_code == 200, r.text
    assert r.json()["prioritized_at"] is None

    eventos = await _eventos(db_session, entry)
    assert [e.event.value for e in eventos] == ["entry_prioritized", "entry_unprioritized"]
    assert eventos[0].payload["reason"] == "Urgencia por dolor"
    assert eventos[0].actor_user_id is not None


@pytest.mark.parametrize("motivo", [None, "", "corto", "Llamar al 11 5555 0101 urgente"])
async def test_priorizar_sin_motivo_valido(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
    motivo: str | None,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    entry = await _entrada(db_session, staff)

    r = await app_client.post(
        f"{URL}/{entry.id}/priority",
        json={"reason": motivo},
        headers=staff.headers["recepcion"],
    )

    assert r.status_code == 422
    assert r.json()["detail"] == "priority_reason_required"
    assert await _eventos(db_session, entry) == []


@pytest.mark.parametrize(
    ("metodo", "sufijo", "cuerpo"),
    [
        ("patch", "", {"notes": "x"}),
        ("post", "/withdraw", None),
        ("post", "/priority", {"reason": "Urgencia por dolor"}),
        ("delete", "/priority", None),
    ],
)
async def test_odontologo_sin_acciones(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
    metodo: str,
    sufijo: str,
    cuerpo: dict[str, str] | None,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    entry = await _entrada(db_session, staff)

    r = await app_client.request(
        metodo.upper(),
        f"{URL}/{entry.id}{sufijo}",
        json=cuerpo,
        headers=staff.headers["odontologo"],
    )

    assert r.status_code == 403


async def test_entrada_ajena_es_404(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    a = await make_staff(db_session, redis_client, settings)
    b = await make_staff(db_session, redis_client, settings)
    entry_b = await _entrada(db_session, b)

    for metodo, sufijo in (("GET", ""), ("POST", "/withdraw"), ("GET", "/events")):
        r = await app_client.request(
            metodo, f"{URL}/{entry_b.id}{sufijo}", headers=a.headers["recepcion"]
        )
        assert r.status_code == 404, (metodo, sufijo, r.text)
        assert r.json()["detail"] == "not_found"
    entrada = await _releer(db_session, WaitingListEntry, entry_b.id)
    assert isinstance(entrada, WaitingListEntry)
    assert entrada.status is WaitingListStatus.WAITING
