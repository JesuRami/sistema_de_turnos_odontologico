"""Cada evento nuevo sella el horario y los recursos vigentes del turno (C-13, S3)."""

from __future__ import annotations

from uuid import UUID

import httpx
import pytest
from app.core.settings import Settings
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tests.appointment_helpers import at, events_of, iso, make_agenda
from tests.conftest import MutableClock
from tests.report_helpers import alta, fijar_reloj, transicion

pytestmark = pytest.mark.integration


async def test_creacion_reprogramacion_y_transiciones_sellan_la_instantanea(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await alta(app_client, agenda, 10, duration=30)
    creado = (await events_of(db_session, UUID(turno)))[0]
    assert (creado.slot_starts_at, creado.slot_ends_at) == (at(10, days=7), at(10, 30, days=7))
    assert creado.professional_id == agenda.staff.professional.id
    assert creado.chair_id == agenda.staff.chair.id

    movido = await app_client.patch(
        f"/api/appointments/{turno}",
        json={"starts_at": iso(11, days=7)},
        headers=agenda.headers["recepcion"],
    )
    assert movido.status_code == 200, movido.text
    fijar_reloj(agenda_clock, at(14, days=7))
    await transicion(app_client, agenda, turno, "present")

    eventos = await events_of(db_session, UUID(turno))
    assert [e.event.value for e in eventos] == ["created", "rescheduled", "present"]
    assert eventos[1].slot_starts_at == at(11, days=7)
    assert eventos[2].slot_starts_at == at(11, days=7)
    assert all(e.professional_id == agenda.staff.professional.id for e in eventos)
    assert all("slot" not in e.payload for e in eventos)
