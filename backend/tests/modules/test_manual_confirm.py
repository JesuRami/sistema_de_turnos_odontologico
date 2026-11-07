"""Confirmación manual desde recepción con la transición existente (C-11, D7; RN-GL-01).

Contrato del endpoint de C-05: no se agrega ninguno nuevo. Datos ficticios (regla 13).
"""

from __future__ import annotations

import httpx
import pytest
from app.core.settings import Settings
from app.models import (
    ActorType,
    AppointmentEvent,
    AppointmentEventType,
    AppointmentOrigin,
    AppointmentStatus,
)
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import MutableClock
from tests.timeline_helpers import Escena, escena

pytestmark = pytest.mark.integration


async def _confirmar(client: httpx.AsyncClient, e: Escena, rol: str) -> httpx.Response:
    return await client.post(
        f"/api/appointments/{e.appointment.id}/transitions",
        json={"to": "confirmed"},
        headers=e.headers[rol],
    )


async def _confirmaciones(db: AsyncSession, e: Escena) -> list[AppointmentEvent]:
    return list(
        (
            await db.scalars(
                select(AppointmentEvent).where(
                    AppointmentEvent.appointment_id == e.appointment.id,
                    AppointmentEvent.event == AppointmentEventType.CONFIRMED,
                )
            )
        ).all()
    )


async def _pendiente(db: AsyncSession, redis: Redis, settings: Settings) -> Escena:
    return await escena(
        db, redis, settings, status=AppointmentStatus.PENDING, origin=AppointmentOrigin.ONLINE
    )


async def test_recepcion_confirma_un_pendiente_con_auditoria(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _pendiente(db_session, redis_client, settings)

    respuesta = await _confirmar(app_client, e, "recepcion")

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["status"] == "confirmed"
    [evento] = await _confirmaciones(db_session, e)
    assert evento.actor_type is ActorType.USER
    assert evento.actor_user_id == e.recepcion.id


async def test_odontologo_no_confirma(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _pendiente(db_session, redis_client, settings)

    respuesta = await _confirmar(app_client, e, "odontologo")

    assert respuesta.status_code == 403
    assert respuesta.json()["detail"] == "forbidden_role"
    assert await _confirmaciones(db_session, e) == []


async def test_confirmar_dos_veces_no_duplica_el_evento(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _pendiente(db_session, redis_client, settings)
    assert (await _confirmar(app_client, e, "recepcion")).status_code == 200

    segunda = await _confirmar(app_client, e, "recepcion")

    assert segunda.status_code in (409, 422)
    assert len(await _confirmaciones(db_session, e)) == 1
