"""Traza de auditoría de la lista de espera (C-12, D9; specs entries y offers).

Una conversión completa por rotación deja `offer_created → offer_expired → offer_created →
offer_accepted` con sus actores, y ningún payload lleva datos personales. Postgres real con commits.
Datos ficticios (regla 13).
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time, timedelta

import pytest
from app.core.settings import Settings
from app.models import (
    ActorType,
    CancellationReason,
    UserRole,
    WaitingListEntry,
    WaitlistEvent,
    WaitlistOffer,
    WaitlistOfferStatus,
)
from app.modules.appointments.audit import Actor
from app.modules.appointments.schemas import TransitionRequest
from app.modules.appointments.service import AppointmentsService
from app.modules.waiting_list.engine import run_waitlist_tick
from app.modules.waiting_list.offers import OffersService
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.factories import (
    make_appointment,
    make_chair,
    make_clinic,
    make_patient,
    make_professional,
    make_schedule_rule,
    make_user,
)
from tests.waitlist_helpers import make_entry

pytestmark = pytest.mark.integration

AHORA = datetime(2030, 1, 7, 11, 0, tzinfo=UTC)
HUECO = AHORA + timedelta(days=2, hours=2)
NOMBRES = ("Primera Espera Ficticia", "Segunda Espera Ficticia")
TELEFONOS = ("+5491155550161", "+5491155550162")


async def test_traza_completa_de_una_conversion(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    async with rem_maker() as s:
        clinic = await make_clinic(s)
        prof = await make_professional(s, clinic)
        chair = await make_chair(s, clinic)
        await make_schedule_rule(
            s, clinic, prof, chair, weekday=2, start_time=time(9), end_time=time(13)
        )
        titular = await make_patient(s, clinic, full_name="Titular Ficticio")
        turno = await make_appointment(
            s, clinic, patient=titular, professional=prof, chair=chair, starts_at=HUECO
        )
        entradas = []
        for nombre, telefono in zip(NOMBRES, TELEFONOS, strict=True):
            paciente = await make_patient(
                s,
                clinic,
                full_name=nombre,
                phone_e164=telefono,
                whatsapp_opt_in=True,
                email=f"{nombre.split()[0].lower()}@example.com",
            )
            entradas.append(
                await make_entry(
                    s,
                    clinic,
                    paciente,
                    date_from=date(2030, 1, 7),
                    date_to=date(2030, 1, 20),
                    notes="Nota operativa ficticia",
                )
            )
        # Antigüedad explícita: en una misma transacción `created_at` empata.
        for i, entrada in enumerate(entradas):
            await s.execute(
                update(WaitingListEntry)
                .where(WaitingListEntry.id == entrada.id)
                .values(created_at=AHORA - timedelta(days=10 - i))
            )
        await s.commit()

    # 1. Recepción cancela: oferta automática a la primera.
    async with rem_maker() as s:
        user = await make_user(s, clinic, role=UserRole.RECEPCION)
        await s.commit()
    recepcion = Actor(
        clinic_id=clinic.id,
        type=ActorType.USER,
        user_id=user.id,
        roles=frozenset({UserRole.RECEPCION}),
    )
    async with rem_maker() as s:
        await AppointmentsService(s, recepcion, AHORA).transition(
            turno.id, TransitionRequest(to="cancelled", reason=CancellationReason.PACIENTE)
        )
    # 2. Vence: rota a la segunda.
    await run_waitlist_tick(rem_maker, settings, now=lambda: AHORA + timedelta(hours=5))
    # 3. La segunda acepta por su link.
    async with rem_maker() as s:
        segunda = await s.scalar(
            select(WaitlistOffer).where(
                WaitlistOffer.entry_id == entradas[1].id,
                WaitlistOffer.status == WaitlistOfferStatus.PENDING,
            )
        )
    assert segunda is not None
    actor_paciente = Actor(clinic_id=clinic.id, type=ActorType.PATIENT_TOKEN)
    async with rem_maker() as s:
        await OffersService(
            s, actor_paciente, AHORA + timedelta(hours=5, minutes=1), settings
        ).accept(segunda.id)

    async with rem_maker() as s:
        eventos = list(
            (
                await s.execute(
                    select(WaitlistEvent)
                    .where(WaitlistEvent.clinic_id == clinic.id)
                    .order_by(WaitlistEvent.created_at, WaitlistEvent.id)
                )
            ).scalars()
        )
    de_ofertas = [(e.event.value, e.actor_type.value) for e in eventos if e.offer_id is not None]
    assert de_ofertas == [
        ("offer_created", "system"),
        ("offer_expired", "system"),
        ("offer_created", "system"),
        ("offer_accepted", "patient_token"),
        ("entry_converted", "patient_token"),
    ]
    volcado = json.dumps([e.payload for e in eventos], ensure_ascii=False)
    for dato in (*NOMBRES, *TELEFONOS, "@example.com", "Nota operativa"):
        assert dato not in volcado
