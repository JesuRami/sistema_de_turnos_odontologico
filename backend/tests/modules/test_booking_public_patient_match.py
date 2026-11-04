"""Match de paciente en la reserva pública (C-07, D7, RN-ON-05): sin duplicados ni pisadas."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
import pytest
from app.core.settings import Settings
from app.models import Appointment, Patient
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.appointment_helpers import iso
from tests.booking_helpers import (
    TELEFONO_E164,
    PublicBooking,
    client_for,
    committed_app,
    make_booking,
    reserva,
)
from tests.conftest import MutableClock
from tests.factories import make_clinic, make_patient

pytestmark = pytest.mark.integration

RECURRENTE = "Paciente Recurrente Ficticio"


def _url(b: PublicBooking) -> str:
    return f"/api/booking/{b.slug}/appointments"


async def _pacientes(db_session: AsyncSession, b: PublicBooking) -> list[Patient]:
    filas = await db_session.execute(
        select(Patient)
        .where(Patient.clinic_id == b.clinic.id)
        .order_by(Patient.created_at)
        .execution_options(populate_existing=True)
    )
    return list(filas.scalars())


async def _turno_de(db_session: AsyncSession, b: PublicBooking) -> Appointment:
    return (
        await db_session.execute(select(Appointment).where(Appointment.clinic_id == b.clinic.id))
    ).scalar_one()


async def test_mismo_telefono_y_nombre_con_otras_mayusculas_reutiliza_al_paciente(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)
    existente = await make_patient(
        db_session, b.clinic, full_name=RECURRENTE, phone_e164=TELEFONO_E164
    )

    response = await app_client.post(
        _url(b),
        json=reserva(b, iso(10), full_name=f"  {RECURRENTE.upper()} "),
    )

    assert response.status_code == 201, response.text
    assert [p.id for p in await _pacientes(db_session, b)] == [existente.id]
    assert (await _turno_de(db_session, b)).patient_id == existente.id


async def test_mismo_telefono_con_otro_nombre_crea_un_paciente_nuevo(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)
    familiar = await make_patient(
        db_session, b.clinic, full_name="Familiar Ficticio", phone_e164=TELEFONO_E164
    )

    response = await app_client.post(_url(b), json=reserva(b, iso(10), full_name=RECURRENTE))

    assert response.status_code == 201, response.text
    pacientes = await _pacientes(db_session, b)
    assert len(pacientes) == 2
    nuevo = next(p for p in pacientes if p.id != familiar.id)
    assert nuevo.phone_e164 == TELEFONO_E164
    assert nuevo.full_name == RECURRENTE
    assert (await _turno_de(db_session, b)).patient_id == nuevo.id


async def test_paciente_archivado_no_se_reutiliza(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)
    archivado = await make_patient(
        db_session,
        b.clinic,
        full_name=RECURRENTE,
        phone_e164=TELEFONO_E164,
        archived_at=datetime(2029, 1, 1, tzinfo=UTC),
    )

    response = await app_client.post(_url(b), json=reserva(b, iso(10), full_name=RECURRENTE))

    assert response.status_code == 201, response.text
    assert (await _turno_de(db_session, b)).patient_id != archivado.id
    assert len(await _pacientes(db_session, b)) == 2


async def test_paciente_de_otra_clinica_con_mismo_telefono_y_nombre_no_se_reutiliza(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)
    otra = await make_clinic(db_session, booking_enabled=True)
    ajeno = await make_patient(db_session, otra, full_name=RECURRENTE, phone_e164=TELEFONO_E164)

    response = await app_client.post(_url(b), json=reserva(b, iso(10), full_name=RECURRENTE))

    assert response.status_code == 201, response.text
    (propio,) = await _pacientes(db_session, b)
    assert propio.id != ajeno.id
    assert propio.clinic_id == b.clinic.id


async def test_recurrente_con_email_distinto_conserva_sus_datos(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)
    existente = await make_patient(
        db_session,
        b.clinic,
        full_name=RECURRENTE,
        phone_e164=TELEFONO_E164,
        email="original@example.com",
    )

    response = await app_client.post(
        _url(b),
        json=reserva(b, iso(10), full_name=RECURRENTE.upper(), email="otro@example.com"),
    )

    assert response.status_code == 201, response.text
    (paciente,) = await _pacientes(db_session, b)
    assert paciente.id == existente.id
    assert paciente.email == "original@example.com"
    assert paciente.full_name == RECURRENTE
    assert paciente.phone_e164 == TELEFONO_E164


async def test_opt_in_pasa_de_false_a_true_y_actualiza_la_privacidad(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    b = await make_booking(db_session)
    await make_patient(
        db_session,
        b.clinic,
        full_name=RECURRENTE,
        phone_e164=TELEFONO_E164,
        whatsapp_opt_in=False,
        privacy_consent_at=datetime(2020, 1, 1, tzinfo=UTC),
        privacy_consent_version="v0-vieja",
    )

    response = await app_client.post(
        _url(b), json=reserva(b, iso(10), full_name=RECURRENTE, whatsapp_opt_in=True)
    )

    assert response.status_code == 201, response.text
    (paciente,) = await _pacientes(db_session, b)
    assert paciente.whatsapp_opt_in is True
    assert paciente.privacy_consent_version == settings.PRIVACY_POLICY_VERSION
    assert paciente.privacy_consent_at is not None
    assert paciente.privacy_consent_at.year == 2030


async def test_opt_in_true_nunca_pasa_a_false(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)
    await make_patient(
        db_session,
        b.clinic,
        full_name=RECURRENTE,
        phone_e164=TELEFONO_E164,
        whatsapp_opt_in=True,
    )

    response = await app_client.post(
        _url(b),
        json=reserva(
            b, iso(10), full_name=RECURRENTE, whatsapp_opt_in=False, email="otro@example.com"
        ),
    )

    assert response.status_code == 201, response.text
    (paciente,) = await _pacientes(db_session, b)
    assert paciente.whatsapp_opt_in is True


async def test_solo_email_nunca_se_matchea_y_crea_paciente_nuevo(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)
    await make_patient(
        db_session, b.clinic, full_name=RECURRENTE, phone_e164=None, email="mismo@example.com"
    )

    response = await app_client.post(
        _url(b),
        json=reserva(
            b,
            iso(10),
            full_name=RECURRENTE,
            phone=None,
            whatsapp_opt_in=None,
            email="mismo@example.com",
        ),
    )

    assert response.status_code == 201, response.text
    assert len(await _pacientes(db_session, b)) == 2


async def _reservar(
    app: FastAPI,
    b: PublicBooking,
    ronda: int,
    i: int,
    hh: int,
    mm: int,
    nombre: str,
    telefono: str,
) -> int:
    async with client_for(app, ip=f"10.0.{ronda}.{i}") as client:
        respuesta = await client.post(
            _url(b), json=reserva(b, iso(hh, mm), full_name=nombre, phone=telefono)
        )
        return respuesta.status_code


async def test_dos_reservas_concurrentes_del_mismo_paciente_nuevo_crean_un_solo_paciente(
    committed_engine: AsyncEngine, redis_client: Redis, settings: Settings
) -> None:
    async with AsyncSession(committed_engine, expire_on_commit=False) as session:
        b = await make_booking(session)
        await session.commit()
    app = committed_app(committed_engine, redis_client, settings)
    horarios = [(9, 0), (9, 30), (10, 0), (10, 30), (11, 0), (11, 30), (12, 0), (12, 30)]

    for ronda in range(4):
        nombre = f"Paciente Carrera {ronda} Ficticio"
        telefono = f"011 15 5555-01{ronda:02d}"
        pares = horarios[2 * ronda : 2 * ronda + 2]

        estados = await asyncio.gather(
            *(
                _reservar(app, b, ronda, i, hh, mm, nombre, telefono)
                for i, (hh, mm) in enumerate(pares)
            )
        )

        assert estados == [201, 201], f"ronda {ronda}"
        async with AsyncSession(committed_engine) as session:
            total = await session.scalar(
                select(func.count())
                .select_from(Patient)
                .where(Patient.clinic_id == b.clinic.id, Patient.full_name == nombre)
            )
        assert total == 1, f"ronda {ronda}"
