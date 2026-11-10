"""Carreras de aceptación con commits reales (C-12, D5; spec waitlist/offers).

Dos aceptaciones del mismo hueco: gana la primera y la segunda vuelve prioritaria. Aceptar mientras
el tick vence la oferta: o hay turno, o la oferta venció, nunca ambos. Datos ficticios (regla 13).
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

import pytest
from app.common.exceptions import DomainError
from app.core.settings import Settings
from app.models import (
    ActorType,
    Appointment,
    WaitingListEntry,
    WaitingListStatus,
    WaitlistOffer,
    WaitlistOfferStatus,
)
from app.modules.appointments.audit import Actor
from app.modules.waiting_list.engine import run_waitlist_tick
from app.modules.waiting_list.offers import OffersService
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.factories import (
    make_chair,
    make_clinic,
    make_patient,
    make_professional,
    make_schedule_rule,
)
from tests.waitlist_helpers import make_entry, make_offer

pytestmark = pytest.mark.integration

AHORA = datetime(2030, 1, 7, 11, 0, tzinfo=UTC)
HUECO = AHORA + timedelta(days=2, hours=2)  # miércoles 10:00 local


@dataclass(frozen=True, slots=True)
class Escena:
    clinic_id: uuid.UUID
    ofertas: list[uuid.UUID]
    entradas: list[uuid.UUID]


async def _escena(engine: AsyncEngine, n: int, *, expires_in: timedelta) -> Escena:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        clinic = await make_clinic(s)
        prof = await make_professional(s, clinic)
        chair = await make_chair(s, clinic)
        await make_schedule_rule(
            s, clinic, prof, chair, weekday=2, start_time=time(9), end_time=time(13)
        )
        ofertas, entradas = [], []
        for i in range(n):
            paciente = await make_patient(
                s, clinic, full_name=f"Espera Ficticia {i}", whatsapp_opt_in=True
            )
            entry = await make_entry(
                s,
                clinic,
                paciente,
                status=WaitingListStatus.OFFERED,
                date_from=date(2030, 1, 7),
                date_to=date(2030, 1, 20),
            )
            offer = await make_offer(
                s,
                entry,
                professional=prof,
                chair=chair,
                starts_at=HUECO,
                now=AHORA,
                expires_in=expires_in,
                mode="manual",
            )
            ofertas.append(offer.id)
            entradas.append(entry.id)
        await s.commit()
    return Escena(clinic.id, ofertas, entradas)


async def _aceptar(
    engine: AsyncEngine, e: Escena, offer_id: uuid.UUID, settings: Settings, now: datetime
) -> str:
    actor = Actor(clinic_id=e.clinic_id, type=ActorType.PATIENT_TOKEN)
    async with AsyncSession(engine, expire_on_commit=False) as s:
        try:
            await OffersService(s, actor, now, settings).accept(offer_id)
        except DomainError as error:
            return error.detail
    return "accepted"


async def _turnos(engine: AsyncEngine, e: Escena) -> int:
    async with AsyncSession(engine) as s:
        return int(
            await s.scalar(
                select(func.count())
                .select_from(Appointment)
                .where(Appointment.clinic_id == e.clinic_id)
            )
            or 0
        )


async def test_dos_aceptaciones_simultaneas_del_mismo_hueco(
    committed_engine: AsyncEngine, settings: Settings
) -> None:
    e = await _escena(committed_engine, 2, expires_in=timedelta(hours=4))

    resultados = await asyncio.gather(
        *(_aceptar(committed_engine, e, o, settings, AHORA) for o in e.ofertas)
    )

    assert await _turnos(committed_engine, e) == 1
    async with AsyncSession(committed_engine) as s:
        entradas = {
            x.id: x
            for x in (
                await s.execute(select(WaitingListEntry).where(WaitingListEntry.id.in_(e.entradas)))
            ).scalars()
        }
    ganadora = e.entradas[resultados.index("accepted")]
    perdedora = next(i for i in e.entradas if i != ganadora)
    assert entradas[ganadora].status is WaitingListStatus.CONVERTED
    assert entradas[perdedora].status is WaitingListStatus.WAITING
    # La perdedora pudo perder dentro de `book` (`slot_taken`, queda prioritaria) o encontrar su
    # oferta ya cerrada por la ganadora (`offer_closed`): en ambos casos no hay segundo turno.
    otra = resultados[1 - resultados.index("accepted")]
    assert otra in {"slot_taken", "offer_closed"}
    if otra == "slot_taken":
        assert entradas[perdedora].priority_reason == "slot_lost"


async def test_aceptar_mientras_el_tick_la_vence(
    committed_engine: AsyncEngine, settings: Settings
) -> None:
    e = await _escena(committed_engine, 1, expires_in=timedelta(hours=1))
    vencimiento = AHORA + timedelta(hours=1)
    fabrica = async_sessionmaker(committed_engine, expire_on_commit=False)

    await asyncio.gather(
        _aceptar(committed_engine, e, e.ofertas[0], settings, vencimiento - timedelta(seconds=1)),
        run_waitlist_tick(fabrica, settings, now=lambda: vencimiento),
    )

    async with AsyncSession(committed_engine) as s:
        oferta = await s.get(WaitlistOffer, e.ofertas[0])
    assert oferta is not None
    turnos = await _turnos(committed_engine, e)
    if oferta.status is WaitlistOfferStatus.ACCEPTED:
        assert turnos == 1
    else:
        assert oferta.status is WaitlistOfferStatus.EXPIRED
        assert turnos == 0
