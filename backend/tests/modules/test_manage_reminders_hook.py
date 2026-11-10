"""Punto de invalidación de recordatorios (C-08, D11): una vez por mutación, en su transacción."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

import httpx
import pytest
from app.models import Appointment, AppointmentStatus
from app.modules.reminders.invalidation import get_reminder_invalidator
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from tests.appointment_helpers import at, reload
from tests.conftest import MutableClock
from tests.manage_helpers import make_managed

pytestmark = pytest.mark.integration

Action = Literal["confirm", "cancel", "reschedule"]


@dataclass
class Spy:
    """Registra cada invocación; opcionalmente falla para probar la atomicidad."""

    fail: bool = False
    calls: list[tuple[uuid.UUID, Action, datetime]] = field(default_factory=list)

    async def invalidated(
        self, session: AsyncSession, appointment: Appointment, *, action: Action
    ) -> None:
        _ = session
        self.calls.append((appointment.id, action, appointment.starts_at))
        if self.fail:
            raise RuntimeError("canal de recordatorios caído (simulado)")


@pytest.fixture()
def spy(app_instance: FastAPI) -> Spy:
    espia = Spy()
    app_instance.dependency_overrides[get_reminder_invalidator] = lambda: espia
    return espia


@pytest.mark.parametrize(
    ("cuerpo", "accion"),
    [
        ({"action": "confirm"}, "confirm"),
        ({"action": "cancel", "reason": "viaje"}, "cancel"),
        ({"action": "reschedule", "starts_at": at(11, days=7).isoformat()}, "reschedule"),
    ],
)
async def test_cada_accion_invoca_el_punto_una_vez(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    agenda_clock: MutableClock,
    spy: Spy,
    cuerpo: dict[str, Any],
    accion: Action,
) -> None:
    managed = await make_managed(db_session, at(10, days=7))
    appointment_id = managed.appointment.id

    response = await app_client.patch(managed.url, json=cuerpo)

    assert response.status_code == 200, response.text
    assert [(i, a) for i, a, _ in spy.calls] == [(appointment_id, accion)]


async def test_la_reprogramacion_llega_con_el_horario_nuevo(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock, spy: Spy
) -> None:
    managed = await make_managed(db_session, at(10, days=7))

    await app_client.patch(
        managed.url, json={"action": "reschedule", "starts_at": at(11, days=7).isoformat()}
    )

    assert [inicio for _, _, inicio in spy.calls] == [at(11, days=7)]


async def test_un_replay_no_invoca_el_punto(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock, spy: Spy
) -> None:
    managed = await make_managed(db_session, at(10, days=7), status=AppointmentStatus.CONFIRMED)

    response = await app_client.patch(managed.url, json={"action": "confirm"})

    assert response.status_code == 200
    assert spy.calls == []


async def test_si_el_punto_falla_la_cancelacion_no_se_persiste(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    agenda_clock: MutableClock,
    spy: Spy,
) -> None:
    spy.fail = True
    managed = await make_managed(db_session, at(10, days=7))
    appointment_id = managed.appointment.id

    response = await app_client.patch(managed.url, json={"action": "cancel"})
    assert response.status_code == 500

    assert (await reload(db_session, appointment_id)).status is AppointmentStatus.PENDING


async def test_con_el_no_op_las_tres_acciones_funcionan(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    uno = await make_managed(db_session, at(10, days=7))
    dos = await make_managed(db_session, at(11, days=7), booking=uno.booking)

    confirmar = await app_client.patch(uno.url, json={"action": "confirm"})
    mover = await app_client.patch(
        uno.url, json={"action": "reschedule", "starts_at": at(12, days=7).isoformat()}
    )
    cancelar = await app_client.patch(dos.url, json={"action": "cancel"})

    assert (confirmar.status_code, mover.status_code, cancelar.status_code) == (200, 200, 200)
