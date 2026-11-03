"""Historial de eventos (solo admin) y atomicidad mutación + auditoría (C-05 8.2, RN-GL-01)."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import httpx
import pytest
from app.core.settings import Settings
from app.models import (
    ActorType,
    Appointment,
    AppointmentEvent,
    AppointmentStatus,
    CancellationReason,
    UserRole,
)
from app.modules.appointments import states
from app.modules.appointments.audit import Actor
from app.modules.appointments.schemas import TransitionRequest
from app.modules.appointments.service import AppointmentsService
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.appointment_helpers import PACIENTE_NOMBRE, at, iso, make_agenda, post
from tests.conftest import MutableClock
from tests.factories import (
    make_appointment,
    make_chair,
    make_clinic,
    make_patient,
    make_professional,
    make_schedule_rule,
    make_user,
)

pytestmark = pytest.mark.integration


async def test_admin_ve_el_historial_en_orden_cronologico_sin_pii(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    creado = (await post(app_client, agenda, at(10, days=7))).json()
    await app_client.patch(
        f"/api/appointments/{creado['id']}",
        json={"starts_at": iso(11, days=7), "notes": "Nota ficticia"},
        headers=agenda.headers["recepcion"],
    )
    await app_client.post(
        f"/api/appointments/{creado['id']}/transitions",
        json={"to": "cancelled", "reason": "paciente"},
        headers=agenda.headers["recepcion"],
    )

    response = await app_client.get(
        f"/api/appointments/{creado['id']}/events", headers=agenda.headers["admin"]
    )

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [e["event"] for e in items] == ["created", "rescheduled", "cancelled"]
    assert items[2]["from_status"] == "confirmed"
    assert items[2]["to_status"] == "cancelled"
    assert all(e["actor_type"] == "user" and e["actor_user_id"] for e in items)
    assert PACIENTE_NOMBRE not in response.text
    assert str(agenda.patient.phone_e164) not in response.text


@pytest.mark.parametrize("rol", ["recepcion", "odontologo"])
async def test_historial_solo_para_admin(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
    rol: str,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    creado = (await post(app_client, agenda, at(10))).json()
    response = await app_client.get(
        f"/api/appointments/{creado['id']}/events", headers=agenda.headers[rol]
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "forbidden_role"


BA = ZoneInfo("America/Argentina/Buenos_Aires")


async def test_falla_de_auditoria_revierte_la_cancelacion(
    committed_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Commits reales: si el evento no se escribe, el turno conserva su estado."""
    inicio = datetime(2030, 1, 14, 10, 0, tzinfo=BA)
    async with AsyncSession(committed_engine, expire_on_commit=False) as session:
        clinic = await make_clinic(session)
        professional = await make_professional(session, clinic)
        chair = await make_chair(session, clinic)
        await make_schedule_rule(session, clinic, professional, chair, start_time=time(9))
        user = await make_user(session, clinic, role=UserRole.RECEPCION)
        turno = await make_appointment(
            session,
            clinic,
            patient=await make_patient(session, clinic),
            professional=professional,
            chair=chair,
            starts_at=inicio,
            created_by_user_id=user.id,
        )
        await session.commit()
    actor = Actor(
        clinic_id=clinic.id,
        type=ActorType.USER,
        user_id=user.id,
        roles=frozenset({UserRole.RECEPCION}),
    )

    async def _evento_roto(session: AsyncSession, *_: object, **__: object) -> None:
        session.add(
            AppointmentEvent(
                clinic_id=clinic.id,
                appointment_id=turno.id,
                actor_type=ActorType.USER,
                actor_user_id=None,  # viola ck_appointment_event_actor_user_coherent
                event="cancelled",
                payload={},
            )
        )
        await session.flush()

    monkeypatch.setattr(states, "record_event", _evento_roto)
    async with AsyncSession(committed_engine) as session:
        with pytest.raises(IntegrityError):
            await AppointmentsService(
                session, actor, datetime(2030, 1, 7, 8, tzinfo=BA)
            ).transition(
                turno.id, TransitionRequest(to="cancelled", reason=CancellationReason.PACIENTE)
            )
        await session.rollback()

    async with AsyncSession(committed_engine) as session:
        releido = await session.get(Appointment, turno.id)
        assert releido is not None
        assert releido.status == AppointmentStatus.CONFIRMED
        assert releido.cancelled_at is None
        eventos = await session.scalar(select(func.count()).select_from(AppointmentEvent))
        assert eventos == 0
