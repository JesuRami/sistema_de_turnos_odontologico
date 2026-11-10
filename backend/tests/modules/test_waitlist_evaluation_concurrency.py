"""Evaluación concurrente de la lista de espera con commits reales (C-12, D3; spec offers).

Sesiones independientes, como requests en producción: dos cancelaciones simultáneas no ofrecen la
misma entrada dos veces y una cancelación nunca espera a una entrada tomada por otra transacción
(`SKIP LOCKED`). Datos ficticios (regla 13).
"""

from __future__ import annotations

import asyncio
import time as reloj
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pytest
from app.models import (
    ActorType,
    CancellationReason,
    Patient,
    UserRole,
    WaitingListEntry,
    WaitingListStatus,
    WaitlistOffer,
)
from app.modules.appointments.audit import Actor
from app.modules.appointments.schemas import TransitionRequest
from app.modules.appointments.service import AppointmentsService
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.factories import (
    make_appointment,
    make_chair,
    make_clinic,
    make_patient,
    make_professional,
    make_user,
)
from tests.waitlist_helpers import make_entry

pytestmark = pytest.mark.integration

AHORA = datetime(2030, 1, 7, 11, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Escena:
    clinic_id: uuid.UUID
    actor: Actor
    turnos: list[uuid.UUID]
    entradas: list[uuid.UUID]


async def _escena(engine: AsyncEngine, *, turnos: int = 2, entradas: int = 1) -> Escena:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        clinic = await make_clinic(s)
        prof = await make_professional(s, clinic)
        chair = await make_chair(s, clinic)
        user = await make_user(s, clinic, role=UserRole.RECEPCION)
        titular = await make_patient(s, clinic, full_name="Titular Ficticio")
        ids_turnos = [
            (
                await make_appointment(
                    s,
                    clinic,
                    patient=titular,
                    professional=prof,
                    chair=chair,
                    starts_at=AHORA + timedelta(days=2, hours=i),
                )
            ).id
            for i in range(turnos)
        ]
        ids_entradas = []
        for i in range(entradas):
            paciente = await make_patient(
                s, clinic, full_name=f"Espera Ficticia {i}", whatsapp_opt_in=True
            )
            entrada = await make_entry(
                s, clinic, paciente, date_from=date(2030, 1, 7), date_to=date(2030, 1, 20)
            )
            ids_entradas.append(entrada.id)
        await s.commit()
    actor = Actor(
        clinic_id=clinic.id,
        type=ActorType.USER,
        user_id=user.id,
        roles=frozenset({UserRole.RECEPCION}),
    )
    return Escena(clinic.id, actor, ids_turnos, ids_entradas)


async def _cancelar(engine: AsyncEngine, e: Escena, turno: uuid.UUID) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await AppointmentsService(s, e.actor, AHORA).transition(
            turno, TransitionRequest(to="cancelled", reason=CancellationReason.PACIENTE)
        )


async def _ofertas(engine: AsyncEngine, e: Escena) -> list[WaitlistOffer]:
    async with AsyncSession(engine) as s:
        return list(
            (
                await s.execute(select(WaitlistOffer).where(WaitlistOffer.clinic_id == e.clinic_id))
            ).scalars()
        )


async def test_dos_cancelaciones_simultaneas_una_sola_oferta(
    committed_engine: AsyncEngine,
) -> None:
    e = await _escena(committed_engine)

    await asyncio.gather(*(_cancelar(committed_engine, e, t) for t in e.turnos))

    [oferta] = await _ofertas(committed_engine, e)
    assert oferta.entry_id == e.entradas[0]


async def test_la_cancelacion_no_espera_a_una_entrada_tomada(
    committed_engine: AsyncEngine,
) -> None:
    e = await _escena(committed_engine, turnos=1, entradas=2)
    async with AsyncSession(committed_engine) as bloqueo:
        # Otra transacción tiene tomada la primera de la cola.
        await bloqueo.execute(
            select(WaitingListEntry).where(WaitingListEntry.id == e.entradas[0]).with_for_update()
        )

        await asyncio.wait_for(_cancelar(committed_engine, e, e.turnos[0]), timeout=5)

        [oferta] = await _ofertas(committed_engine, e)
        assert oferta.entry_id == e.entradas[1]
        await bloqueo.rollback()


async def test_mil_entradas_no_compatibles_no_frenan_la_cancelacion(
    committed_engine: AsyncEngine,
) -> None:
    e = await _escena(committed_engine, turnos=1, entradas=0)
    async with AsyncSession(committed_engine) as s:
        pacientes = (
            await s.execute(
                insert(Patient)
                .values(
                    [
                        {
                            "clinic_id": e.clinic_id,
                            "full_name": f"Masivo Ficticio {i}",
                            "phone_e164": f"+549115555{i:04d}",
                            "whatsapp_opt_in": True,
                        }
                        for i in range(1000)
                    ]
                )
                .returning(Patient.id)
            )
        ).scalars()
        await s.execute(
            insert(WaitingListEntry).values(
                [
                    {
                        "clinic_id": e.clinic_id,
                        "patient_id": pid,
                        "date_from": date(2030, 1, 7),
                        "date_to": date(2030, 1, 20),
                        "weekdays": [6],  # domingo: no le sirve el hueco
                        "status": WaitingListStatus.WAITING,
                        "source": "reception",
                    }
                    for pid in pacientes
                ]
            )
        )
        await s.commit()

    inicio = reloj.monotonic()
    await _cancelar(committed_engine, e, e.turnos[0])
    duracion = reloj.monotonic() - inicio

    assert await _ofertas(committed_engine, e) == []
    assert duracion < 2.0, f"la cancelación tardó {duracion:.2f} s"
