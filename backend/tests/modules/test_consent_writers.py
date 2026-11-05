"""Los escritores del opt-in de WhatsApp pasan por `ConsentService` (C-09, spec core/patients)."""

from __future__ import annotations

import httpx
import pytest
from app.core.settings import Settings
from app.models import (
    Consent,
    ConsentSource,
    ConsentStatus,
    Patient,
    ReminderChannel,
    User,
    UserRole,
)
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.agenda_helpers import make_staff
from tests.appointment_helpers import iso
from tests.booking_helpers import TELEFONO_E164, make_booking, reserva
from tests.conftest import MutableClock
from tests.factories import make_patient

pytestmark = pytest.mark.integration

NOMBRE = "Irma Ficticia Consentida"


async def _consentimientos(session: AsyncSession, clinic_id: object) -> list[Consent]:
    return list(
        (
            await session.execute(
                select(Consent)
                .where(Consent.clinic_id == clinic_id)
                .order_by(Consent.changed_at)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )


async def _paciente(session: AsyncSession, clinic_id: object, nombre: str) -> Patient:
    return (
        await session.execute(
            select(Patient)
            .where(Patient.clinic_id == clinic_id, Patient.full_name == nombre)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def test_alta_por_recepcion_con_whatsapp_registra_opt_in_con_el_usuario(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)

    response = await app_client.post(
        "/api/patients",
        json={"full_name": NOMBRE, "phone": "011 15 5555-0141", "whatsapp_opt_in": True},
        headers=staff.headers["recepcion"],
    )

    assert response.status_code == 201, response.text
    paciente = await _paciente(db_session, staff.clinic.id, NOMBRE)
    recepcion = (
        await db_session.execute(
            select(User).where(User.clinic_id == staff.clinic.id, User.role == UserRole.RECEPCION)
        )
    ).scalar_one()
    [fila] = await _consentimientos(db_session, staff.clinic.id)
    assert paciente.whatsapp_opt_in is True
    assert (fila.patient_id, fila.channel, fila.status, fila.source) == (
        paciente.id,
        ReminderChannel.WHATSAPP,
        ConsentStatus.OPT_IN,
        ConsentSource.RECEPTION,
    )
    assert fila.changed_by_user_id == recepcion.id


async def test_alta_sin_autorizacion_no_genera_consentimiento(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)

    response = await app_client.post(
        "/api/patients",
        json={"full_name": NOMBRE, "phone": "011 15 5555-0142"},
        headers=staff.headers["recepcion"],
    )

    assert response.status_code == 201, response.text
    assert (await _paciente(db_session, staff.clinic.id, NOMBRE)).whatsapp_opt_in is False
    assert await _consentimientos(db_session, staff.clinic.id) == []


async def test_reserva_publica_de_paciente_nuevo_registra_opt_in_de_booking(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)

    response = await app_client.post(
        f"/api/booking/{b.slug}/appointments", json=reserva(b, iso(10), full_name=NOMBRE)
    )

    assert response.status_code == 201, response.text
    paciente = await _paciente(db_session, b.clinic.id, NOMBRE)
    [fila] = await _consentimientos(db_session, b.clinic.id)
    assert paciente.whatsapp_opt_in is True
    assert (fila.patient_id, fila.status, fila.source) == (
        paciente.id,
        ConsentStatus.OPT_IN,
        ConsentSource.BOOKING,
    )
    assert fila.changed_by_user_id is None


async def test_match_sin_opt_in_que_acepta_registra_una_fila(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)
    existente = await make_patient(
        db_session, b.clinic, full_name=NOMBRE, phone_e164=TELEFONO_E164, whatsapp_opt_in=False
    )

    response = await app_client.post(
        f"/api/booking/{b.slug}/appointments", json=reserva(b, iso(10), full_name=NOMBRE)
    )

    assert response.status_code == 201, response.text
    await db_session.refresh(existente)
    [fila] = await _consentimientos(db_session, b.clinic.id)
    assert existente.whatsapp_opt_in is True
    assert (fila.patient_id, fila.source) == (existente.id, ConsentSource.BOOKING)


async def test_match_con_opt_in_previo_no_agrega_consentimiento(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)
    await make_patient(
        db_session, b.clinic, full_name=NOMBRE, phone_e164=TELEFONO_E164, whatsapp_opt_in=True
    )

    response = await app_client.post(
        f"/api/booking/{b.slug}/appointments", json=reserva(b, iso(10), full_name=NOMBRE)
    )

    assert response.status_code == 201, response.text
    assert await _consentimientos(db_session, b.clinic.id) == []


async def test_la_fusion_no_hereda_ni_crea_consentimiento(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    con_opt_in = await make_patient(
        db_session, staff.clinic, full_name="Duplicada Con Opt-in", whatsapp_opt_in=True
    )
    conservada = await make_patient(
        db_session, staff.clinic, full_name="Conservada Sin Opt-in", whatsapp_opt_in=False
    )

    response = await app_client.post(
        f"/api/patients/{con_opt_in.id}/merge",
        json={"into_patient_id": str(conservada.id)},
        headers=staff.headers["recepcion"],
    )

    assert response.status_code == 200, response.text
    await db_session.refresh(conservada)
    assert conservada.whatsapp_opt_in is False
    assert await _consentimientos(db_session, staff.clinic.id) == []
