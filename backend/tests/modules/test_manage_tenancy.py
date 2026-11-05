"""Aislamiento por clínica en la gestión por token (C-08, regla 4)."""

from __future__ import annotations

import httpx
import pytest
from app.models import AppointmentEvent, AppointmentStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.appointment_helpers import at, reload
from tests.conftest import MutableClock
from tests.factories import make_appointment, make_patient
from tests.manage_helpers import make_managed, new_token

pytestmark = pytest.mark.integration


async def test_el_token_de_b_solo_alcanza_su_turno_y_no_toca_a(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    clinica_a = await make_managed(db_session, at(10, days=7))
    clinica_b = await make_managed(db_session, at(10, days=7))
    ids = (clinica_a.appointment.id, clinica_b.appointment.id)

    vista_b = await app_client.get(clinica_b.url)
    cancelar_b = await app_client.patch(clinica_b.url, json={"action": "cancel"})
    ajeno = await app_client.get(f"/api/manage/{new_token()}")

    assert vista_b.json()["clinic"]["name"] == clinica_b.booking.clinic.name
    assert clinica_a.booking.clinic.slug not in vista_b.text
    assert cancelar_b.status_code == 200
    assert ajeno.json() == {"detail": "manage_link_not_found"}
    assert (await reload(db_session, ids[0])).status is AppointmentStatus.PENDING
    assert (await reload(db_session, ids[1])).status is AppointmentStatus.CANCELLED


async def test_mutar_por_token_escribe_eventos_solo_en_la_clinica_del_turno(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    clinica_a = await make_managed(db_session, at(10, days=7))
    clinica_b = await make_managed(db_session, at(10, days=7))
    clinic_ids = (clinica_a.booking.clinic.id, clinica_b.booking.clinic.id)

    await app_client.patch(clinica_b.url, json={"action": "confirm"})

    clinicas = set(
        (
            await db_session.execute(
                select(AppointmentEvent.clinic_id).where(AppointmentEvent.clinic_id.in_(clinic_ids))
            )
        ).scalars()
    )
    assert clinicas == {clinic_ids[1]}


async def test_la_disponibilidad_de_a_no_cruza_turnos_de_b(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    """B tiene un turno a las 11:00; ese horario se sigue ofreciendo en A."""
    clinica_a = await make_managed(db_session, at(10, days=7))
    clinica_b = await make_managed(db_session, at(10, days=7))
    b = clinica_b.booking
    await make_appointment(
        db_session,
        b.clinic,
        patient=await make_patient(db_session, b.clinic),
        professional=b.professional,
        chair=b.chair,
        starts_at=at(11, days=7),
    )

    response = await app_client.get(
        f"{clinica_a.url}/availability",
        params={"from": at(0, days=7).isoformat(), "to": at(0, days=8).isoformat()},
    )

    assert at(11, days=7).isoformat() in [s["starts_at"] for s in response.json()["slots"]]
