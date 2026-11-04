"""Reserva pública (C-07, D4/D5): validación de contacto, consentimientos, éxito y grilla."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest
from app.core.settings import Settings
from app.models import (
    Appointment,
    AppointmentOrigin,
    AppointmentStatus,
    Patient,
    UserRole,
)
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.appointment_helpers import at, iso
from tests.auth_helpers import issue_session
from tests.booking_helpers import (
    EMAIL,
    NOMBRE,
    TELEFONO_E164,
    TELEFONO_NACIONAL,
    PublicBooking,
    make_booking,
    reserva,
)
from tests.conftest import AGENDA_NOW, MutableClock
from tests.factories import (
    make_appointment,
    make_chair,
    make_patient,
    make_schedule_rule,
    make_user,
    unique_email,
)

pytestmark = pytest.mark.integration


def _url(b: PublicBooking) -> str:
    return f"/api/booking/{b.slug}/appointments"


async def _conteos(db_session: AsyncSession, b: PublicBooking) -> tuple[int, int]:
    pacientes = await db_session.scalar(
        select(func.count()).select_from(Patient).where(Patient.clinic_id == b.clinic.id)
    )
    turnos = await db_session.scalar(
        select(func.count()).select_from(Appointment).where(Appointment.clinic_id == b.clinic.id)
    )
    return int(pacientes or 0), int(turnos or 0)


def _sin_datos_del_paciente(texto: str) -> None:
    for dato in (NOMBRE, "Lucía", "Inventada", TELEFONO_NACIONAL, "5555", "0123", "lucia"):
        assert dato not in texto, dato


# ---------------------------------------------------------------- validación


@pytest.mark.parametrize(
    ("paciente", "detalle"),
    [
        ({"phone": None, "whatsapp_opt_in": None}, "contact_required"),
        ({"privacy_accepted": False}, "privacy_consent_required"),
        ({"whatsapp_opt_in": False}, "whatsapp_opt_in_required"),
        ({"phone": None, "whatsapp_opt_in": None, "email": "no-es-un-email"}, "contact_required"),
        ({"phone": "12ab", "whatsapp_opt_in": True}, "contact_required"),
        ({"whatsapp_opt_in": None}, "whatsapp_opt_in_required"),
    ],
    ids=[
        "sin contacto",
        "sin privacidad",
        "telefono sin opt-in ni email",
        "email invalido",
        "telefono invalido sin email",
        "telefono sin elegir opt-in",
    ],
)
async def test_validaciones_de_contacto_y_consentimiento_no_crean_nada(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    agenda_clock: MutableClock,
    caplog: pytest.LogCaptureFixture,
    paciente: dict[str, Any],
    detalle: str,
) -> None:
    caplog.set_level(logging.DEBUG)
    b = await make_booking(db_session)
    antes = await _conteos(db_session, b)

    response = await app_client.post(_url(b), json=reserva(b, iso(10), **paciente))

    assert response.status_code == 422, response.text
    assert response.json() == {"detail": detalle}
    assert await _conteos(db_session, b) == antes
    _sin_datos_del_paciente(response.text)
    _sin_datos_del_paciente(caplog.text)


@pytest.mark.parametrize(
    "extra",
    [
        {"duration_min": 15},
        {"chair_id": "00000000-0000-0000-0000-000000000001"},
        {"status": "confirmed"},
        {"origin": "reception"},
        {"clinic_id": "00000000-0000-0000-0000-000000000002"},
    ],
)
async def test_campos_no_permitidos_son_422_sin_eco_de_datos(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    agenda_clock: MutableClock,
    caplog: pytest.LogCaptureFixture,
    extra: dict[str, Any],
) -> None:
    caplog.set_level(logging.DEBUG)
    b = await make_booking(db_session)
    antes = await _conteos(db_session, b)

    response = await app_client.post(_url(b), json={**reserva(b, iso(10)), **extra})

    assert response.status_code == 422
    assert await _conteos(db_session, b) == antes
    _sin_datos_del_paciente(response.text)
    _sin_datos_del_paciente(caplog.text)


async def test_starts_at_sin_zona_es_422_sin_eco_de_datos(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)

    response = await app_client.post(_url(b), json=reserva(b, "2030-01-07T10:00:00"))

    assert response.status_code == 422
    _sin_datos_del_paciente(response.text)
    assert await _conteos(db_session, b) == (0, 0)


async def test_slug_inexistente_en_reserva_es_404(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)

    response = await app_client.post(
        "/api/booking/no-existe-xyz/appointments", json=reserva(b, iso(10))
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "booking_not_found"}


# -------------------------------------------------------------------- éxito


async def test_telefono_nacional_con_opt_in_crea_turno_pendiente_online(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    b = await make_booking(db_session, slot_duration_min=45)

    response = await app_client.post(_url(b), json=reserva(b, iso(9, 45)))

    assert response.status_code == 201, response.text
    cuerpo = response.json()
    assert cuerpo["channel"] == "whatsapp"
    assert cuerpo["warnings"] == []
    assert cuerpo["professional_id"] == str(b.professional.id)
    assert datetime.fromisoformat(cuerpo["starts_at"]) == at(9, 45)
    assert datetime.fromisoformat(cuerpo["ends_at"]) == at(10, 30)
    paciente = (
        await db_session.execute(select(Patient).where(Patient.clinic_id == b.clinic.id))
    ).scalar_one()
    assert paciente.phone_e164 == TELEFONO_E164
    assert paciente.whatsapp_opt_in is True
    assert paciente.full_name == NOMBRE
    assert paciente.privacy_consent_version == settings.PRIVACY_POLICY_VERSION
    assert paciente.privacy_consent_at == AGENDA_NOW
    turno = (
        await db_session.execute(select(Appointment).where(Appointment.clinic_id == b.clinic.id))
    ).scalar_one()
    assert turno.status == AppointmentStatus.PENDING
    assert turno.origin == AppointmentOrigin.ONLINE
    assert turno.is_overbooking is False
    assert turno.created_by_user_id is None
    assert turno.patient_id == paciente.id
    assert turno.ends_at - turno.starts_at == timedelta(minutes=45)


async def test_telefono_invalido_con_email_usa_email_y_descarta_el_telefono(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)

    response = await app_client.post(
        _url(b),
        json=reserva(b, iso(10), phone="12ab", whatsapp_opt_in=None, email=EMAIL.upper()),
    )

    assert response.status_code == 201, response.text
    assert response.json()["channel"] == "email"
    assert response.json()["warnings"] == ["phone_invalid_email_channel"]
    paciente = (
        await db_session.execute(select(Patient).where(Patient.clinic_id == b.clinic.id))
    ).scalar_one()
    assert paciente.phone_e164 is None
    assert paciente.email == EMAIL
    assert paciente.whatsapp_opt_in is False


async def test_whatsapp_rechazado_con_email_reserva_por_email(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)

    response = await app_client.post(
        _url(b), json=reserva(b, iso(10), whatsapp_opt_in=False, email=EMAIL)
    )

    assert response.status_code == 201, response.text
    assert response.json()["channel"] == "email"
    assert response.json()["warnings"] == ["whatsapp_declined_email_channel"]
    paciente = (
        await db_session.execute(select(Patient).where(Patient.clinic_id == b.clinic.id))
    ).scalar_one()
    assert paciente.phone_e164 == TELEFONO_E164
    assert paciente.whatsapp_opt_in is False


async def test_solo_email_reserva_por_email_sin_aviso(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)

    response = await app_client.post(
        _url(b), json=reserva(b, iso(10), phone=None, whatsapp_opt_in=None, email=EMAIL)
    )

    assert response.status_code == 201, response.text
    assert response.json()["channel"] == "email"
    assert response.json()["warnings"] == []


async def test_el_turno_aparece_en_la_agenda_de_recepcion(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    b = await make_booking(db_session)
    recepcion = await make_user(
        db_session,
        b.clinic,
        email=unique_email("recepcion.ficticia"),
        role=UserRole.RECEPCION,
        must_change_password=False,
    )
    headers = (await issue_session(redis_client, settings, recepcion)).headers
    reservado = await app_client.post(_url(b), json=reserva(b, iso(10)))
    assert reservado.status_code == 201, reservado.text

    agenda = await app_client.get(
        "/api/appointments",
        params={"from": at(0).isoformat(), "to": at(0, days=1).isoformat()},
        headers=headers,
    )

    assert agenda.status_code == 200, agenda.text
    (item,) = agenda.json()["items"]
    assert item["status"] == "pending"
    assert item["origin"] == "online"
    assert item["patient"]["full_name"] == NOMBRE


# ------------------------------------------------------------------- grilla


@pytest.mark.parametrize(
    ("hh", "mm"), [(9, 10), (8, 30), (13, 0), (12, 45)], ids=["09:10", "08:30", "13:00", "12:45"]
)
async def test_inicio_fuera_de_grilla_u_horario_es_slot_not_offered(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    agenda_clock: MutableClock,
    hh: int,
    mm: int,
) -> None:
    b = await make_booking(db_session)

    response = await app_client.post(_url(b), json=reserva(b, iso(hh, mm)))

    assert response.status_code == 422
    assert response.json() == {"detail": "slot_not_offered"}
    assert await _conteos(db_session, b) == (0, 0)


async def test_otro_dia_de_la_semana_es_slot_not_offered(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)

    response = await app_client.post(_url(b), json=reserva(b, iso(10, days=1)))

    assert response.status_code == 422
    assert response.json() == {"detail": "slot_not_offered"}


async def test_inicio_pasado_es_appointment_in_past(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)
    agenda_clock.current = at(10, 15)

    response = await app_client.post(_url(b), json=reserva(b, iso(10)))

    assert response.status_code == 422
    assert response.json() == {"detail": "appointment_in_past"}
    assert await _conteos(db_session, b) == (0, 0)


async def test_dos_sillones_a_la_misma_hora_uno_ocupado_usa_el_libre(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)
    sillon_b = await make_chair(db_session, b.clinic, name="Sillón Ficticio Dos")
    await make_schedule_rule(db_session, b.clinic, b.professional, sillon_b)
    # Otro profesional ocupa el sillón de menor id a las 10:00.
    otro = await make_booking(db_session, clinic=b.clinic)
    otro_paciente = await make_patient(db_session, b.clinic)
    primero, segundo = sorted((b.chair, sillon_b), key=lambda c: c.id)
    await make_appointment(
        db_session,
        b.clinic,
        patient=otro_paciente,
        professional=otro.professional,
        chair=primero,
        starts_at=at(10),
    )

    response = await app_client.post(_url(b), json=reserva(b, iso(10)))

    assert response.status_code == 201, response.text
    turno = (
        await db_session.execute(
            select(Appointment).where(
                Appointment.professional_id == b.professional.id,
                Appointment.origin == AppointmentOrigin.ONLINE,
            )
        )
    ).scalar_one()
    assert turno.chair_id == segundo.id


async def test_con_ambos_sillones_libres_elige_el_de_menor_id(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)
    sillon_b = await make_chair(db_session, b.clinic, name="Sillón Ficticio Dos")
    await make_schedule_rule(db_session, b.clinic, b.professional, sillon_b)

    response = await app_client.post(_url(b), json=reserva(b, iso(10)))

    assert response.status_code == 201, response.text
    turno = (
        await db_session.execute(select(Appointment).where(Appointment.clinic_id == b.clinic.id))
    ).scalar_one()
    assert turno.chair_id == min(b.chair.id, sillon_b.id)
