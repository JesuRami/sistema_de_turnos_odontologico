"""Costo de `reconcile` en el camino caliente de crear, mover y cancelar (C-09, D3 / tarea 6.6)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import httpx
import pytest
from app.core.settings import Settings
from redis.asyncio import Redis
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from tests.appointment_helpers import at, iso, make_agenda, post, seed
from tests.conftest import MutableClock
from tests.reminder_helpers import statuses_of

pytestmark = pytest.mark.integration


@contextmanager
def _contar(db_session: AsyncSession) -> Iterator[list[str]]:
    """Sentencias SQL que tocan las tablas del motor (o la configuración de pasos)."""
    vistas: list[str] = []
    motor = db_session.bind.sync_engine

    def _escucha(conn: object, cursor: object, statement: str, *rest: object) -> None:
        if any(t in statement for t in ("reminder_job", "reminder_steps", "delivery_event")):
            vistas.append(" ".join(statement.split())[:70])

    event.listen(motor, "before_cursor_execute", _escucha)
    try:
        yield vistas
    finally:
        event.remove(motor, "before_cursor_execute", _escucha)


async def test_crear_un_turno_agrega_pocas_sentencias_del_motor(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)

    with _contar(db_session) as sentencias:
        response = await post(app_client, agenda, at(10, days=7))

    assert response.status_code == 201, response.text
    # lectura de pasos + lectura de jobs + alta + pasos futuros (insert multi-fila)
    assert len(sentencias) <= 5, sentencias


async def test_mover_y_cancelar_agregan_pocas_sentencias_del_motor(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    creado = await post(app_client, agenda, at(10, days=7))
    turno_id = uuid.UUID(creado.json()["id"])

    with _contar(db_session) as al_mover:
        mover = await app_client.patch(
            f"/api/appointments/{turno_id}",
            json={"starts_at": iso(11, days=14)},
            headers=agenda.headers["recepcion"],
        )
    with _contar(db_session) as al_cancelar:
        cancelar = await app_client.post(
            f"/api/appointments/{turno_id}/transitions",
            json={"to": "cancelled", "reason": "paciente"},
            headers=agenda.headers["recepcion"],
        )

    assert (mover.status_code, cancelar.status_code) == (200, 200)
    # lectura de pasos + de jobs + un UPDATE por job recalculado (4) y ese cierre en lote
    assert len(al_mover) <= 7, al_mover
    # lectura de pasos + de jobs + cierre en lote + sus eventos
    assert len(al_cancelar) <= 6, al_cancelar
    assert set((await statuses_of(db_session, turno_id)).values()) == {"cancelled"}
    _ = seed
