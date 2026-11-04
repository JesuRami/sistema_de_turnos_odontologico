"""Aislamiento cross-tenant de la reserva pública (C-07, regla 4): todo bajo UN `clinic_id`."""

from __future__ import annotations

from datetime import datetime

import httpx
import pytest
from app.models import Appointment, AppointmentEvent, Patient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.appointment_helpers import at, iso
from tests.booking_helpers import PublicBooking, make_booking, reserva
from tests.conftest import MutableClock
from tests.factories import make_appointment, make_block, make_patient

pytestmark = pytest.mark.integration


def _url(b: PublicBooking) -> str:
    return f"/api/booking/{b.slug}/appointments"


def _params(b: PublicBooking, professional_id: object) -> dict[str, str]:
    return {
        "professional_id": str(professional_id),
        "from": at(0).isoformat(),
        "to": at(0, days=1).isoformat(),
    }


async def _filas(db_session: AsyncSession, b: PublicBooking) -> tuple[int, int, int]:
    """(pacientes, turnos, eventos) de la clínica de `b`."""
    pacientes = await db_session.scalar(
        select(func.count()).select_from(Patient).where(Patient.clinic_id == b.clinic.id)
    )
    turnos = await db_session.scalar(
        select(func.count()).select_from(Appointment).where(Appointment.clinic_id == b.clinic.id)
    )
    eventos = await db_session.scalar(
        select(func.count())
        .select_from(AppointmentEvent)
        .where(AppointmentEvent.clinic_id == b.clinic.id)
    )
    return int(pacientes or 0), int(turnos or 0), int(eventos or 0)


async def test_un_turno_de_otra_clinica_no_quita_el_hueco(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    a = await make_booking(db_session)
    otra = await make_booking(db_session)
    ajeno = await make_patient(db_session, otra.clinic)
    await make_appointment(
        db_session,
        otra.clinic,
        patient=ajeno,
        professional=otra.professional,
        chair=otra.chair,
        starts_at=at(10),
    )
    await make_block(
        db_session, otra.clinic, professional=otra.professional, starts_at=at(9), ends_at=at(13)
    )

    response = await app_client.get(
        f"/api/booking/{a.slug}/availability", params=_params(a, a.professional.id)
    )

    inicios = [datetime.fromisoformat(s["starts_at"]) for s in response.json()["slots"]]
    assert at(10) in inicios
    assert len(inicios) == 8


async def test_slug_de_a_con_profesional_de_b_es_404_y_b_no_registra_cambios(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    a = await make_booking(db_session)
    otra = await make_booking(db_session)
    antes = await _filas(db_session, otra)

    disponibilidad = await app_client.get(
        f"/api/booking/{a.slug}/availability", params=_params(a, otra.professional.id)
    )
    cuerpo = reserva(a, iso(10))
    cuerpo["professional_id"] = str(otra.professional.id)
    reservada = await app_client.post(_url(a), json=cuerpo)

    for response in (disponibilidad, reservada):
        assert response.status_code == 404
        assert response.json() == {"detail": "professional_not_found"}
    assert await _filas(db_session, otra) == antes
    assert await _filas(db_session, a) == (0, 0, 0)


async def test_el_match_nunca_reutiliza_pacientes_de_otra_clinica(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    a = await make_booking(db_session)
    otra = await make_booking(db_session)
    ajeno = await make_patient(
        db_session,
        otra.clinic,
        full_name="Lucía Inventada Ficticia",
        phone_e164="+5491155550123",
        whatsapp_opt_in=False,
    )

    response = await app_client.post(_url(a), json=reserva(a, iso(10)))

    assert response.status_code == 201, response.text
    await db_session.refresh(ajeno)
    assert ajeno.whatsapp_opt_in is False
    assert ajeno.privacy_consent_at is None
    assert await _filas(db_session, otra) == (1, 0, 0)
    assert (await _filas(db_session, a))[0] == 1
