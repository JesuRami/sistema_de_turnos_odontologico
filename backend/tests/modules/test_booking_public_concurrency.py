"""Carrera por el hueco y 409 público (C-07, D6): un ganador, alternativos sin datos ajenos."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import httpx
import pytest
from app.core.settings import Settings
from app.models import Appointment, AppointmentOrigin, Patient, UserRole
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.appointment_helpers import at, iso
from tests.auth_helpers import issue_session
from tests.booking_helpers import (
    PublicBooking,
    client_for,
    committed_app,
    make_booking,
    reserva,
)
from tests.conftest import MutableClock
from tests.factories import (
    make_appointment,
    make_block,
    make_patient,
    make_user,
    unique_email,
)

pytestmark = pytest.mark.integration

RONDAS = 20


def _tel(a: int, b: int) -> str:
    return f"011 15 5555-{a:02d}{b:02d}"


async def _post(
    app: FastAPI,
    url: str,
    ip: str,
    cuerpo: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    async with client_for(app, ip=ip) as client:
        return await client.post(url, json=cuerpo, headers=headers)


def _url(b: PublicBooking) -> str:
    return f"/api/booking/{b.slug}/appointments"


def _assert_409_publico(response: httpx.Response, *ids_ajenos: object) -> list[dict[str, str]]:
    assert response.status_code == 409, response.text
    cuerpo = response.json()
    assert cuerpo["detail"] == "slot_taken"
    assert set(cuerpo) == {"detail", "alternatives"}
    alternativas: list[dict[str, str]] = cuerpo["alternatives"]
    assert len(alternativas) <= 3
    for alternativa in alternativas:
        assert set(alternativa) == {"starts_at", "ends_at", "professional_id"}
    for dato in ("conflicts", "chair", "blocks", *map(str, ids_ajenos)):
        assert dato not in response.text, dato
    return alternativas


# ------------------------------------------------------------- secuencial


async def test_hueco_ocupado_da_409_con_alternativos_publicos(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)
    ocupante = await make_patient(db_session, b.clinic, full_name="Ocupante Ficticio")
    turno = await make_appointment(
        db_session,
        b.clinic,
        patient=ocupante,
        professional=b.professional,
        chair=b.chair,
        starts_at=at(10),
    )

    response = await app_client.post(_url(b), json=reserva(b, iso(10)))

    alternativas = _assert_409_publico(response, turno.id, ocupante.id, b.chair.id)
    assert [datetime.fromisoformat(a["starts_at"]) for a in alternativas] == [
        at(10, 30),
        at(11),
        at(11, 30),
    ]
    assert {a["professional_id"] for a in alternativas} == {str(b.professional.id)}
    total = await db_session.scalar(
        select(func.count()).select_from(Patient).where(Patient.clinic_id == b.clinic.id)
    )
    assert total == 1  # solo el ocupante: la reserva perdedora no dejó paciente


async def test_hueco_bloqueado_tambien_se_reduce_a_slot_taken(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)
    bloqueo = await make_block(
        db_session, b.clinic, professional=b.professional, starts_at=at(10), ends_at=at(10, 30)
    )

    response = await app_client.post(_url(b), json=reserva(b, iso(10)))

    alternativas = _assert_409_publico(response, bloqueo.id)
    assert at(10, 30) in [datetime.fromisoformat(a["starts_at"]) for a in alternativas]


async def test_profesional_ocupado_en_un_sillon_no_ofrece_ese_hueco_en_el_otro(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    from tests.factories import make_chair, make_schedule_rule

    b = await make_booking(db_session)
    sillon_b = await make_chair(db_session, b.clinic, name="Sillón Ficticio Dos")
    await make_schedule_rule(db_session, b.clinic, b.professional, sillon_b)
    ocupante = await make_patient(db_session, b.clinic, full_name="Ocupante Ficticio")
    await make_appointment(
        db_session,
        b.clinic,
        patient=ocupante,
        professional=b.professional,
        chair=b.chair,
        starts_at=at(10),
    )

    response = await app_client.post(_url(b), json=reserva(b, iso(10)))

    # El profesional sigue ocupado en 10:00 aunque el otro sillón esté libre.
    alternativas = _assert_409_publico(response)
    assert [datetime.fromisoformat(a["starts_at"]) for a in alternativas][0] == at(10, 30)


# -------------------------------------------------------------- concurrencia


async def test_dos_reservas_online_por_el_mismo_hueco_un_201_y_un_409(
    committed_engine: AsyncEngine, redis_client: Redis, settings: Settings
) -> None:
    async with AsyncSession(committed_engine, expire_on_commit=False) as session:
        b = await make_booking(session)
        await session.commit()
    app = committed_app(committed_engine, redis_client, settings)

    for ronda in range(RONDAS):
        dia, franja = divmod(ronda, 4)
        inicio = iso(9 + franja, 0, days=7 * dia)

        r1, r2 = await asyncio.gather(
            _post(
                app,
                _url(b),
                f"10.1.{ronda}.1",
                reserva(b, inicio, full_name=f"Paciente Uno Ronda {ronda}", phone=_tel(ronda, 1)),
            ),
            _post(
                app,
                _url(b),
                f"10.1.{ronda}.2",
                reserva(b, inicio, full_name=f"Paciente Dos Ronda {ronda}", phone=_tel(ronda, 2)),
            ),
        )

        estados = sorted((r1.status_code, r2.status_code))
        assert estados == [201, 409], f"ronda {ronda}: {r1.text} {r2.text}"
        perdedora = r1 if r1.status_code == 409 else r2
        _assert_409_publico(perdedora)
        async with AsyncSession(committed_engine) as session:
            en_hueco = await session.scalar(
                select(func.count())
                .select_from(Appointment)
                .where(
                    Appointment.professional_id == b.professional.id,
                    Appointment.starts_at == datetime.fromisoformat(inicio),
                )
            )
            nuevos = await session.scalar(
                select(func.count())
                .select_from(Patient)
                .where(Patient.full_name.like(f"% Ronda {ronda}"))
            )
        assert en_hueco == 1
        assert nuevos == 1, "el perdedor no debe dejar paciente nuevo"


async def test_recepcion_vs_online_por_el_mismo_hueco_gana_uno_solo(
    committed_engine: AsyncEngine, redis_client: Redis, settings: Settings
) -> None:
    async with AsyncSession(committed_engine, expire_on_commit=False) as session:
        b = await make_booking(session)
        recepcion = await make_user(
            session,
            b.clinic,
            email=unique_email("recepcion.ficticia"),
            role=UserRole.RECEPCION,
            must_change_password=False,
        )
        paciente = await make_patient(session, b.clinic, full_name="Paciente Recepcion Ficticio")
        await session.commit()
        headers = (await issue_session(redis_client, settings, recepcion)).headers
    app = committed_app(committed_engine, redis_client, settings)

    for ronda in range(10):
        dia, franja = divmod(ronda, 4)
        inicio = iso(9 + franja, 0, days=7 * dia)
        nombre = f"Paciente Online Ronda {ronda}"

        alta = {
            "patient_id": str(paciente.id),
            "professional_id": str(b.professional.id),
            "chair_id": str(b.chair.id),
            "starts_at": inicio,
        }
        rec, onl = await asyncio.gather(
            _post(app, "/api/appointments", "10.2.0.1", alta, headers),
            _post(
                app,
                _url(b),
                f"10.2.1.{ronda}",
                reserva(b, inicio, full_name=nombre, phone=_tel(50 + ronda, 0)),
            ),
        )

        assert sorted((rec.status_code, onl.status_code)) == [201, 409], f"{rec.text} {onl.text}"
        async with AsyncSession(committed_engine) as session:
            creados = await session.scalar(
                select(func.count()).select_from(Patient).where(Patient.full_name == nombre)
            )
            online = await session.scalar(
                select(func.count())
                .select_from(Appointment)
                .where(
                    Appointment.origin == AppointmentOrigin.ONLINE,
                    Appointment.starts_at == datetime.fromisoformat(inicio),
                )
            )
        if onl.status_code == 409:
            _assert_409_publico(onl)
            assert (creados, online) == (0, 0)
        else:
            assert (creados, online) == (1, 1)
