"""Evaluación de la lista de espera al cancelar (C-12, D3; spec waitlist/offers).

Postgres y Redis reales; reloj de la app en `AGENDA_NOW` (lunes 07/01/2030 08:00 local). La
cancelación pasa por la API real (recepción) o por el link de gestión (paciente). Datos ficticios
(regla 13).
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import date, time, timedelta
from typing import Any

import httpx
import pytest
from app.core.settings import Settings
from app.models import (
    Appointment,
    AppointmentOrigin,
    AppointmentStatus,
    Patient,
    ReminderChannel,
    ReminderJob,
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
from tests.factories import (
    make_appointment,
    make_block,
    make_chair,
    make_patient,
    make_professional,
    make_schedule_rule,
)
from tests.waitlist_helpers import make_entry, make_offer

pytestmark = pytest.mark.integration

# Miércoles 09/01/2030 10:00 local (13:00 UTC).
HUECO = AGENDA_NOW + timedelta(days=2, hours=2)


@dataclass
class Escena:
    staff: Staff
    turno: Appointment
    espera: Patient


async def _escena(
    db: AsyncSession,
    redis: Redis,
    settings: Settings,
    *,
    starts_at: Any = HUECO,
    **turno: Any,
) -> Escena:
    staff = await make_staff(db, redis, settings)
    titular = await make_patient(db, staff.clinic, full_name="Titular Ficticio")
    espera = await make_patient(
        db, staff.clinic, full_name="Paciente Espera Ficticia", whatsapp_opt_in=True
    )
    cita = await make_appointment(
        db,
        staff.clinic,
        patient=titular,
        professional=staff.professional,
        chair=staff.chair,
        starts_at=starts_at,
        **turno,
    )
    return Escena(staff, cita, espera)


async def _cancelar(client: httpx.AsyncClient, e: Escena) -> httpx.Response:
    return await client.post(
        f"/api/appointments/{e.turno.id}/transitions",
        json={"to": "cancelled", "reason": "paciente"},
        headers=e.staff.headers["recepcion"],
    )


async def _ofertas(db: AsyncSession, clinic_id: Any) -> list[WaitlistOffer]:
    return list(
        (
            await db.execute(
                select(WaitlistOffer)
                .where(WaitlistOffer.clinic_id == clinic_id)
                .execution_options(populate_existing=True)
            )
        ).scalars()
    )


async def _entrada(db: AsyncSession, e: Escena, **cambios: Any) -> WaitingListEntry:
    valores: dict[str, Any] = {
        "professional": e.staff.professional,
        "date_from": date(2030, 1, 7),
        "date_to": date(2030, 1, 20),
    }
    valores.update(cambios)
    paciente = valores.pop("patient", e.espera)
    return await make_entry(db, e.staff.clinic, paciente, **valores)


async def test_cancelacion_crea_la_oferta_en_el_mismo_commit(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, settings)
    entry = await _entrada(db_session, e)

    r = await _cancelar(app_client, e)

    assert r.status_code == 200, r.text
    [oferta] = await _ofertas(db_session, e.staff.clinic.id)
    assert oferta.status is WaitlistOfferStatus.PENDING
    assert oferta.entry_id == entry.id
    assert (oferta.professional_id, oferta.chair_id) == (e.staff.professional.id, e.staff.chair.id)
    assert (oferta.starts_at, oferta.ends_at) == (e.turno.starts_at, e.turno.ends_at)
    assert oferta.source_appointment_id == e.turno.id
    assert oferta.mode == "auto"
    # TTL completo: el hueco está a dos días.
    assert oferta.expires_at == AGENDA_NOW + timedelta(hours=4)
    await db_session.refresh(entry)
    assert entry.status is WaitingListStatus.OFFERED
    job = await db_session.scalar(
        select(ReminderJob).where(ReminderJob.waitlist_offer_id == oferta.id)
    )
    assert job is not None
    assert job.channel is ReminderChannel.WHATSAPP
    assert job.step == "waitlist_offer"
    assert job.available_at == AGENDA_NOW
    evento = await db_session.scalar(
        select(WaitlistEvent).where(WaitlistEvent.offer_id == oferta.id)
    )
    assert evento is not None and evento.event.value == "offer_created"
    assert evento.actor_type.value == "system"


async def test_cancelacion_por_link_de_gestion(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    token = secrets.token_urlsafe(32)
    e = await _escena(
        db_session,
        redis_client,
        settings,
        origin=AppointmentOrigin.ONLINE,
        status=AppointmentStatus.PENDING,
        manage_token_hash=hashlib.sha256(token.encode()).digest(),
    )
    await _entrada(db_session, e)

    r = await app_client.patch(f"/api/manage/{token}", json={"action": "cancel"})

    assert r.status_code == 200, r.text
    assert len(await _ofertas(db_session, e.staff.clinic.id)) == 1


async def test_sin_entradas_compatibles(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, settings)

    r = await _cancelar(app_client, e)

    assert r.status_code == 200
    assert await _ofertas(db_session, e.staff.clinic.id) == []


async def test_reprogramar_no_ofrece(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, settings)
    await make_schedule_rule(
        db_session, e.staff.clinic, e.staff.professional, e.staff.chair, weekday=2
    )
    await _entrada(db_session, e)

    r = await app_client.patch(
        f"/api/appointments/{e.turno.id}",
        json={"starts_at": (HUECO + timedelta(minutes=30)).isoformat()},
        headers=e.staff.headers["recepcion"],
    )

    assert r.status_code == 200, r.text
    assert await _ofertas(db_session, e.staff.clinic.id) == []


async def test_no_show_no_evalua(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, settings, starts_at=AGENDA_NOW - timedelta(hours=1))
    await _entrada(db_session, e, date_from=date(2030, 1, 7))

    r = await app_client.post(
        f"/api/appointments/{e.turno.id}/transitions",
        json={"to": "no_show"},
        headers=e.staff.headers["recepcion"],
    )

    assert r.status_code == 200, r.text
    assert await _ofertas(db_session, e.staff.clinic.id) == []


@pytest.mark.parametrize(
    "caso",
    [
        "otro_profesional",
        "fuera_del_periodo",
        "fuera_de_la_franja",
        "dia_no_elegido",
        "archivado",
        "sin_canal",
        "ocupado",
        "ya_ofrecido",
    ],
)
async def test_entradas_no_compatibles(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
    caso: str,
) -> None:
    e = await _escena(db_session, redis_client, settings)
    cambios: dict[str, Any] = {}
    if caso == "otro_profesional":
        cambios["professional"] = await make_professional(db_session, e.staff.clinic)
    elif caso == "fuera_del_periodo":
        cambios.update(date_from=date(2030, 1, 10), date_to=date(2030, 1, 20))
    elif caso == "fuera_de_la_franja":
        # El hueco es 10:00–10:30 local; la franja empieza a las 10:15.
        cambios.update(time_from=time(10, 15), time_to=time(18, 0))
    elif caso == "dia_no_elegido":
        cambios["weekdays"] = [0, 3]  # el hueco es miércoles (2)
    elif caso == "archivado":
        e.espera.archived_at = AGENDA_NOW
    elif caso == "sin_canal":
        e.espera.whatsapp_opt_in = False
        e.espera.email = None
    elif caso == "ocupado":
        # Turno del mismo paciente superpuesto con el hueco, con otro profesional y otro sillón.
        await make_appointment(
            db_session,
            e.staff.clinic,
            patient=e.espera,
            professional=await make_professional(db_session, e.staff.clinic),
            chair=await make_chair(db_session, e.staff.clinic),
            starts_at=HUECO + timedelta(minutes=15),
        )
    await db_session.flush()
    entry = await _entrada(db_session, e, **cambios)
    if caso == "ya_ofrecido":
        await make_offer(
            db_session,
            entry,
            professional=e.staff.professional,
            chair=e.staff.chair,
            starts_at=HUECO,
            now=AGENDA_NOW - timedelta(hours=5),
            expires_in=timedelta(hours=1),
            status=WaitlistOfferStatus.EXPIRED,
        )

    r = await _cancelar(app_client, e)

    assert r.status_code == 200, r.text
    pendientes = [
        o
        for o in await _ofertas(db_session, e.staff.clinic.id)
        if o.status is WaitlistOfferStatus.PENDING
    ]
    assert pendientes == []


async def test_franja_que_contiene_el_hueco(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, settings)
    await _entrada(db_session, e, time_from=time(10, 0), time_to=time(10, 30), weekdays=[2])

    await _cancelar(app_client, e)

    assert len(await _ofertas(db_session, e.staff.clinic.id)) == 1


async def test_cualquiera_es_compatible(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, settings)
    await _entrada(db_session, e, professional=None)

    await _cancelar(app_client, e)

    assert len(await _ofertas(db_session, e.staff.clinic.id)) == 1


async def test_orden_prioritaria_y_fifo(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, settings)
    vieja = await _entrada(db_session, e)
    otra = await make_patient(db_session, e.staff.clinic, whatsapp_opt_in=True)
    prioritaria = await _entrada(
        db_session,
        e,
        patient=otra,
        prioritized_at=AGENDA_NOW,
        priority_reason="Urgencia por dolor",
    )

    await _cancelar(app_client, e)

    [oferta] = await _ofertas(db_session, e.staff.clinic.id)
    assert oferta.entry_id == prioritaria.id
    assert oferta.entry_id != vieja.id


async def test_fifo_con_filtro(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, settings)
    await _entrada(db_session, e, weekdays=[4])  # más antigua, no le sirve el miércoles
    otra = await make_patient(db_session, e.staff.clinic, whatsapp_opt_in=True)
    segunda = await _entrada(db_session, e, patient=otra)

    await _cancelar(app_client, e)

    [oferta] = await _ofertas(db_session, e.staff.clinic.id)
    assert oferta.entry_id == segunda.id


async def test_hueco_bloqueado(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, settings)
    await _entrada(db_session, e)
    await make_block(
        db_session,
        e.staff.clinic,
        chair=e.staff.chair,
        starts_at=HUECO - timedelta(hours=1),
        ends_at=HUECO + timedelta(hours=2),
    )

    await _cancelar(app_client, e)

    assert await _ofertas(db_session, e.staff.clinic.id) == []


@pytest.mark.parametrize(
    ("empieza_en", "vence_en"),
    [
        (timedelta(hours=3), timedelta(hours=2)),  # recortada a inicio − 60 min
        (timedelta(minutes=70), None),  # menos de 15 min de ventana: no se ofrece
        (timedelta(minutes=76), timedelta(minutes=16)),
    ],
)
async def test_ventana_de_la_oferta(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
    empieza_en: timedelta,
    vence_en: timedelta | None,
) -> None:
    e = await _escena(db_session, redis_client, settings, starts_at=AGENDA_NOW + empieza_en)
    await _entrada(db_session, e)

    await _cancelar(app_client, e)

    ofertas = await _ofertas(db_session, e.staff.clinic.id)
    if vence_en is None:
        assert ofertas == []
    else:
        [oferta] = ofertas
        assert oferta.expires_at == AGENDA_NOW + vence_en


async def test_canal_email_sin_opt_in(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, settings)
    e.espera.whatsapp_opt_in = False
    e.espera.email = "espera.ficticia@example.com"
    await db_session.flush()
    await _entrada(db_session, e)

    await _cancelar(app_client, e)

    [oferta] = await _ofertas(db_session, e.staff.clinic.id)
    job = await db_session.scalar(
        select(ReminderJob).where(ReminderJob.waitlist_offer_id == oferta.id)
    )
    assert job is not None and job.channel is ReminderChannel.EMAIL


async def test_borde_de_las_23_30_local(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    # Martes 08/01 23:30 local = miércoles 09/01 02:30 UTC.
    martes_noche = AGENDA_NOW + timedelta(days=1, hours=15, minutes=30)
    e = await _escena(db_session, redis_client, settings, starts_at=martes_noche)
    entry = await _entrada(db_session, e, date_from=date(2030, 1, 8), date_to=date(2030, 1, 8))
    otra = await make_patient(db_session, e.staff.clinic, whatsapp_opt_in=True)
    await _entrada(db_session, e, patient=otra, date_from=date(2030, 1, 9))

    await _cancelar(app_client, e)

    [oferta] = await _ofertas(db_session, e.staff.clinic.id)
    assert oferta.entry_id == entry.id
