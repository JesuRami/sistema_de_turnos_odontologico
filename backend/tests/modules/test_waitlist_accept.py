"""Aceptar una oferta crea el turno `waitlist` (C-12, D5; specs offers y agenda/appointments).

Postgres y Redis reales; recepción acepta en nombre del paciente por la API. Reloj de la app en
`AGENDA_NOW` (lunes 07/01/2030 08:00 local). Datos ficticios (regla 13).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time, timedelta
from typing import Any

import httpx
import pytest
from app.common.exceptions import DomainError
from app.core.settings import Settings
from app.models import (
    ActorType,
    Appointment,
    AppointmentEvent,
    AppointmentOrigin,
    AppointmentStatus,
    Patient,
    ReminderJob,
    WaitingListEntry,
    WaitingListStatus,
    WaitlistOffer,
    WaitlistOfferStatus,
)
from app.modules.appointments.audit import Actor
from app.modules.appointments.service import AppointmentsService, Booking
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.agenda_helpers import Staff, make_staff
from tests.conftest import AGENDA_NOW, MutableClock
from tests.factories import (
    make_appointment,
    make_chair,
    make_clinic,
    make_patient,
    make_professional,
    make_schedule_rule,
)
from tests.waitlist_helpers import make_entry, make_offer

pytestmark = pytest.mark.integration

# Miércoles 09/01/2030 10:00 local (13:00 UTC); regla de los miércoles 09:00–13:00 de 30 min.
HUECO = AGENDA_NOW + timedelta(days=2, hours=2)
URL = "/api/waiting-list/offers"


@dataclass
class Escena:
    staff: Staff
    paciente: Patient
    entry: WaitingListEntry
    offer: WaitlistOffer


async def _escena(
    db: AsyncSession,
    redis: Redis,
    settings: Settings,
    *,
    staff: Staff | None = None,
    **oferta: Any,
) -> Escena:
    if staff is None:
        staff = await make_staff(db, redis, settings)
        await make_schedule_rule(
            db,
            staff.clinic,
            staff.professional,
            staff.chair,
            weekday=2,
            start_time=time(9),
            end_time=time(13),
        )
    paciente = await make_patient(db, staff.clinic, whatsapp_opt_in=True)
    entry = await make_entry(
        db,
        staff.clinic,
        paciente,
        status=WaitingListStatus.OFFERED,
        date_from=date(2030, 1, 7),
        date_to=date(2030, 1, 20),
    )
    valores: dict[str, Any] = {"now": AGENDA_NOW}
    valores.update(oferta)
    offer = await make_offer(
        db,
        entry,
        professional=staff.professional,
        chair=staff.chair,
        starts_at=valores.pop("starts_at", HUECO),
        **valores,
    )
    return Escena(staff, paciente, entry, offer)


async def _aceptar(client: httpx.AsyncClient, e: Escena) -> httpx.Response:
    return await client.post(f"{URL}/{e.offer.id}/accept", headers=e.staff.headers["recepcion"])


async def _turnos(db: AsyncSession, e: Escena) -> list[Appointment]:
    return list(
        (
            await db.execute(
                select(Appointment).where(
                    Appointment.clinic_id == e.staff.clinic.id,
                    Appointment.patient_id == e.paciente.id,
                )
            )
        ).scalars()
    )


async def _releer(db: AsyncSession, fila: Any) -> Any:
    await db.refresh(fila)
    return fila


async def test_aceptar_crea_el_turno_waitlist(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, settings)

    r = await _aceptar(app_client, e)

    assert r.status_code == 200, r.text
    [turno] = await _turnos(db_session, e)
    assert turno.origin is AppointmentOrigin.WAITLIST
    assert turno.status is AppointmentStatus.CONFIRMED
    assert not turno.is_overbooking and turno.manage_token_hash is None
    assert (turno.starts_at, turno.ends_at) == (e.offer.starts_at, e.offer.ends_at)
    assert r.json()["appointment_id"] == str(turno.id)
    oferta = await _releer(db_session, e.offer)
    assert oferta.status is WaitlistOfferStatus.ACCEPTED
    assert oferta.appointment_id == turno.id
    entrada = await _releer(db_session, e.entry)
    assert entrada.status is WaitingListStatus.CONVERTED
    evento = await db_session.scalar(
        select(AppointmentEvent).where(AppointmentEvent.appointment_id == turno.id)
    )
    assert evento is not None
    assert evento.payload["origin"] == "waitlist"
    assert evento.payload["waitlist_offer_id"] == str(e.offer.id)
    assert evento.actor_type.value == "user"
    recordatorios = await db_session.scalar(
        select(func.count()).select_from(ReminderJob).where(ReminderJob.appointment_id == turno.id)
    )
    assert recordatorios and recordatorios > 0


async def test_oferta_paralela_del_mismo_hueco_se_cierra(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, settings)
    otra = await _escena(db_session, redis_client, settings, staff=e.staff, mode="manual")

    r = await _aceptar(app_client, e)

    assert r.status_code == 200, r.text
    oferta = await _releer(db_session, otra.offer)
    assert oferta.status is WaitlistOfferStatus.CANCELLED
    assert oferta.closed_reason == "slot_taken"
    entrada = await _releer(db_session, otra.entry)
    assert entrada.status is WaitingListStatus.WAITING
    assert entrada.prioritized_at is None


async def test_doble_aceptacion_es_idempotente(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, settings)

    primera = await _aceptar(app_client, e)
    segunda = await _aceptar(app_client, e)

    assert primera.status_code == segunda.status_code == 200
    assert primera.json()["appointment_id"] == segunda.json()["appointment_id"]
    assert len(await _turnos(db_session, e)) == 1


@pytest.mark.parametrize(
    ("cambios", "detalle"),
    [
        ({"expires_in": timedelta(minutes=-1)}, "offer_expired"),
        ({"status": WaitlistOfferStatus.DECLINED}, "offer_closed"),
        ({"status": WaitlistOfferStatus.CANCELLED}, "offer_closed"),
    ],
)
async def test_aceptacion_rechazada_sin_cambios(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
    cambios: dict[str, Any],
    detalle: str,
) -> None:
    e = await _escena(db_session, redis_client, settings, **cambios)

    r = await _aceptar(app_client, e)

    assert r.status_code == 409, r.text
    assert r.json()["detail"] == detalle
    assert await _turnos(db_session, e) == []


async def test_paciente_ocupado(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, settings)
    await make_appointment(
        db_session,
        e.staff.clinic,
        patient=e.paciente,
        professional=await make_professional(db_session, e.staff.clinic),
        chair=await make_chair(db_session, e.staff.clinic),
        starts_at=HUECO,
    )

    r = await _aceptar(app_client, e)

    assert r.status_code == 409
    assert r.json()["detail"] == "patient_busy"
    oferta = await _releer(db_session, e.offer)
    assert oferta.status is WaitlistOfferStatus.PENDING


async def test_sobreturno_encima_no_se_acepta(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, settings)
    titular = await make_patient(db_session, e.staff.clinic)
    await make_appointment(
        db_session,
        e.staff.clinic,
        patient=titular,
        professional=e.staff.professional,
        chair=e.staff.chair,
        starts_at=HUECO,
        is_overbooking=True,
        overbooking_reason="Urgencia ficticia",
    )

    r = await _aceptar(app_client, e)

    assert r.status_code == 409
    assert r.json()["detail"] == "slot_taken"
    assert not any(t.is_overbooking for t in await _turnos(db_session, e))


async def test_hueco_ocupado_por_recepcion(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, settings)
    titular = await make_patient(db_session, e.staff.clinic)
    await make_appointment(
        db_session,
        e.staff.clinic,
        patient=titular,
        professional=e.staff.professional,
        chair=e.staff.chair,
        starts_at=HUECO,
    )

    r = await _aceptar(app_client, e)

    assert r.status_code == 409, r.text
    cuerpo = r.json()
    assert cuerpo["detail"] == "slot_taken"
    assert 1 <= len(cuerpo["alternatives"]) <= 3
    assert all(set(a) == {"starts_at", "ends_at"} for a in cuerpo["alternatives"])
    assert "conflicts" not in cuerpo
    oferta = await _releer(db_session, e.offer)
    assert oferta.status is WaitlistOfferStatus.CANCELLED
    assert oferta.closed_reason == "slot_taken"
    entrada = await _releer(db_session, e.entry)
    assert entrada.status is WaitingListStatus.WAITING
    assert entrada.priority_reason == "slot_lost"
    assert entrada.prioritized_at is not None


async def test_turno_waitlist_en_el_pasado(db_session: AsyncSession) -> None:
    clinic = await make_clinic(db_session)
    prof = await make_professional(db_session, clinic)
    chair = await make_chair(db_session, clinic)
    paciente = await make_patient(db_session, clinic)
    servicio = AppointmentsService(
        db_session, Actor(clinic_id=clinic.id, type=ActorType.PATIENT_TOKEN), AGENDA_NOW
    )

    with pytest.raises(DomainError) as error:
        await servicio.book(
            Booking(
                patient_id=paciente.id,
                professional_id=prof.id,
                chair_id=chair.id,
                starts_at=AGENDA_NOW - timedelta(hours=1),
                duration_min=30,
            ),
            origin=AppointmentOrigin.WAITLIST,
        )

    assert error.value.detail == "appointment_in_past"


async def test_odontologo_no_acepta(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, settings)

    r = await app_client.post(f"{URL}/{e.offer.id}/accept", headers=e.staff.headers["odontologo"])

    assert r.status_code == 403
