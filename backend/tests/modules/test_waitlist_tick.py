"""Tick de la lista de espera: vencimientos, rotación y entradas vencidas (C-12, D4).

Postgres real con commits (sesiones del worker). Datos ficticios (regla 13).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from app.core.settings import Settings
from app.models import (
    ActorType,
    Appointment,
    AppointmentEvent,
    Chair,
    Clinic,
    Professional,
    WaitingListEntry,
    WaitingListStatus,
    WaitlistOffer,
    WaitlistOfferStatus,
)
from app.modules.appointments.audit import Actor
from app.modules.waiting_list.engine import run_waitlist_tick
from app.modules.waiting_list.offers import OffersService
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.factories import (
    make_appointment,
    make_chair,
    make_clinic,
    make_patient,
    make_professional,
)
from tests.waitlist_helpers import make_entry, make_offer

pytestmark = pytest.mark.integration

AHORA = datetime(2030, 1, 7, 15, 0, tzinfo=UTC)  # lunes 12:00 local
HUECO = AHORA + timedelta(days=2)


@dataclass
class Escena:
    clinic: Clinic
    professional: Professional
    chair: Chair


async def _escena(maker: async_sessionmaker[AsyncSession]) -> Escena:
    async with maker() as s:
        clinic = await make_clinic(s)
        e = Escena(clinic, await make_professional(s, clinic), await make_chair(s, clinic))
        await s.commit()
    return e


async def _entrada(
    maker: async_sessionmaker[AsyncSession], e: Escena, **cambios: Any
) -> WaitingListEntry:
    async with maker() as s:
        paciente = await make_patient(s, e.clinic, whatsapp_opt_in=True)
        valores: dict[str, Any] = {"date_from": date(2030, 1, 7), "date_to": date(2030, 1, 20)}
        valores.update(cambios)
        entry = await make_entry(s, e.clinic, paciente, **valores)
        await s.commit()
    return entry


async def _ofrecida(
    maker: async_sessionmaker[AsyncSession], e: Escena, **cambios: Any
) -> tuple[WaitingListEntry, WaitlistOffer]:
    entry = await _entrada(maker, e, status=WaitingListStatus.OFFERED, **cambios)
    async with maker() as s:
        offer = await make_offer(
            s,
            entry,
            professional=e.professional,
            chair=e.chair,
            starts_at=HUECO,
            now=AHORA - timedelta(hours=5),
            expires_in=timedelta(hours=4),  # venció hace una hora
        )
        await s.commit()
    return entry, offer


async def _leer(maker: async_sessionmaker[AsyncSession], modelo: Any, id_: Any) -> Any:
    async with maker() as s:
        return await s.get(modelo, id_)


async def _tick(maker: async_sessionmaker[AsyncSession], settings: Settings) -> Any:
    return await run_waitlist_tick(maker, settings, now=lambda: AHORA)


async def test_vence_y_rota_a_la_siguiente(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    e = await _escena(rem_maker)
    entry, offer = await _ofrecida(rem_maker, e)
    siguiente = await _entrada(rem_maker, e)

    stats = await _tick(rem_maker, settings)

    assert (stats.expired_offers, stats.rotated) == (1, 1)
    vencida = await _leer(rem_maker, WaitlistOffer, offer.id)
    assert vencida.status is WaitlistOfferStatus.EXPIRED
    primera = await _leer(rem_maker, WaitingListEntry, entry.id)
    assert primera.status is WaitingListStatus.WAITING
    assert primera.consecutive_expired == 1
    async with rem_maker() as s:
        nueva = await s.scalar(
            select(WaitlistOffer).where(
                WaitlistOffer.entry_id == siguiente.id,
                WaitlistOffer.status == WaitlistOfferStatus.PENDING,
            )
        )
    assert nueva is not None
    assert nueva.starts_at == HUECO


async def test_no_vuelve_a_ofrecer_el_mismo_hueco_a_quien_lo_dejo_vencer(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    e = await _escena(rem_maker)
    entry, _ = await _ofrecida(rem_maker, e)

    await _tick(rem_maker, settings)

    async with rem_maker() as s:
        pendientes = await s.scalar(
            select(func.count())
            .select_from(WaitlistOffer)
            .where(
                WaitlistOffer.entry_id == entry.id,
                WaitlistOffer.status == WaitlistOfferStatus.PENDING,
            )
        )
    assert pendientes == 0


async def test_rotacion_con_el_hueco_ya_ocupado(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    e = await _escena(rem_maker)
    await _ofrecida(rem_maker, e)
    siguiente = await _entrada(rem_maker, e)
    async with rem_maker() as s:
        titular = await make_patient(s, e.clinic)
        await make_appointment(
            s,
            e.clinic,
            patient=titular,
            professional=e.professional,
            chair=e.chair,
            starts_at=HUECO,
        )
        await s.commit()

    stats = await _tick(rem_maker, settings)

    assert stats.rotated == 0
    assert (await _leer(rem_maker, WaitingListEntry, siguiente.id)).status is (
        WaitingListStatus.WAITING
    )


async def test_tercer_vencimiento_cierra_la_entrada(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    e = await _escena(rem_maker)
    entry, _ = await _ofrecida(rem_maker, e, consecutive_expired=2)

    await _tick(rem_maker, settings)

    cerrada = await _leer(rem_maker, WaitingListEntry, entry.id)
    assert cerrada.status is WaitingListStatus.EXPIRED
    assert cerrada.closed_reason == "no_response"


async def test_rechazo_intermedio_reinicia_el_contador(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    # Dos vencidas (contador en 2), un rechazo real y otra vencida: sigue en la cola.
    e = await _escena(rem_maker)
    entry = await _entrada(rem_maker, e, status=WaitingListStatus.OFFERED, consecutive_expired=2)
    async with rem_maker() as s:
        pendiente = await make_offer(
            s,
            entry,
            professional=e.professional,
            chair=e.chair,
            starts_at=HUECO + timedelta(hours=1),
            now=AHORA,
        )
        await s.commit()
    actor = Actor(clinic_id=e.clinic.id, type=ActorType.PATIENT_TOKEN)
    async with rem_maker() as s:
        await OffersService(s, actor, AHORA, settings).decline(pendiente.id)
    assert (await _leer(rem_maker, WaitingListEntry, entry.id)).consecutive_expired == 0
    async with rem_maker() as s:
        fila = await s.get(WaitingListEntry, entry.id)
        assert fila is not None
        fila.status = WaitingListStatus.OFFERED
        await make_offer(
            s,
            fila,
            professional=e.professional,
            chair=e.chair,
            starts_at=HUECO,
            now=AHORA - timedelta(hours=5),
            expires_in=timedelta(hours=4),
        )
        await s.commit()

    await _tick(rem_maker, settings)

    sigue = await _leer(rem_maker, WaitingListEntry, entry.id)
    assert sigue.status is WaitingListStatus.WAITING
    assert sigue.consecutive_expired == 1


async def test_entrada_con_periodo_terminado(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    e = await _escena(rem_maker)
    vencida = await _entrada(rem_maker, e, date_from=date(2030, 1, 1), date_to=date(2030, 1, 6))
    ultimo_dia = await _entrada(rem_maker, e, date_from=date(2030, 1, 1), date_to=date(2030, 1, 7))

    stats = await _tick(rem_maker, settings)

    assert stats.expired_entries == 1
    cerrada = await _leer(rem_maker, WaitingListEntry, vencida.id)
    assert cerrada.status is WaitingListStatus.EXPIRED
    assert cerrada.closed_reason == "range_elapsed"
    assert (await _leer(rem_maker, WaitingListEntry, ultimo_dia.id)).status is (
        WaitingListStatus.WAITING
    )


async def test_dos_ticks_concurrentes(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    e = await _escena(rem_maker)
    _, offer = await _ofrecida(rem_maker, e)
    await _entrada(rem_maker, e)

    resultados = await asyncio.gather(_tick(rem_maker, settings), _tick(rem_maker, settings))

    assert sum(r.expired_offers for r in resultados) == 1
    assert sum(r.rotated for r in resultados) <= 1
    async with rem_maker() as s:
        pendientes = await s.scalar(
            select(func.count())
            .select_from(WaitlistOffer)
            .where(
                WaitlistOffer.clinic_id == e.clinic.id,
                WaitlistOffer.status == WaitlistOfferStatus.PENDING,
            )
        )
    assert pendientes == 1
    assert (await _leer(rem_maker, WaitlistOffer, offer.id)).status is WaitlistOfferStatus.EXPIRED


async def test_ningun_turno_cambia(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    e = await _escena(rem_maker)
    await _ofrecida(rem_maker, e)
    await _entrada(rem_maker, e)
    async with rem_maker() as s:
        antes_turnos = await s.scalar(select(func.count()).select_from(Appointment))
        antes_eventos = await s.scalar(select(func.count()).select_from(AppointmentEvent))

    await _tick(rem_maker, settings)

    async with rem_maker() as s:
        assert await s.scalar(select(func.count()).select_from(Appointment)) == antes_turnos
        assert await s.scalar(select(func.count()).select_from(AppointmentEvent)) == antes_eventos
