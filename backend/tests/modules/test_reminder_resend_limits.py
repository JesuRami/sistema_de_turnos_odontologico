"""Cooldown, tope diario y concurrencia del reenvío manual (C-11, D6; spec manual-actions).

Postgres real; la carrera usa dos sesiones con commits reales sobre la base del módulo.
Datos ficticios (regla 13).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from app.common.exceptions import DomainError
from app.core.settings import Settings
from app.models import ActorType, ReminderChannel, ReminderStatus, UserRole
from app.modules.appointments.audit import Actor
from app.modules.reminders.manual import resend
from app.modules.reminders.schemas import ResendAccepted
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.conftest import MutableClock
from tests.factories import make_user
from tests.reminder_helpers import AHORA, commit_job, commit_scene
from tests.timeline_helpers import NOW, escena, job, reenvio, resend_url, resends_of

pytestmark = pytest.mark.integration


async def test_doble_clic_dentro_del_cooldown_es_409(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await escena(db_session, redis_client, settings)
    fila = await job(db_session, e.appointment, status=ReminderStatus.FAILED)
    url = resend_url(e.appointment.id)

    primera = await app_client.post(url, headers=e.headers["recepcion"])
    agenda_clock.advance(seconds=10)
    segunda = await app_client.post(url, headers=e.headers["recepcion"])

    assert primera.status_code == 202
    assert segunda.status_code == 409
    assert segunda.json()["detail"] == "resend_cooldown"
    assert segunda.json()["retry_after_s"] == 50
    assert await resends_of(db_session, fila.id) == 1


async def test_reenvio_en_cola_tras_el_cooldown_sigue_siendo_cooldown(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await escena(db_session, redis_client, settings)
    await job(db_session, e.appointment, status=ReminderStatus.FAILED)
    url = resend_url(e.appointment.id)
    assert (await app_client.post(url, headers=e.headers["recepcion"])).status_code == 202

    agenda_clock.advance(minutes=5)
    respuesta = await app_client.post(url, headers=e.headers["recepcion"])

    assert respuesta.status_code == 409
    assert respuesta.json()["detail"] == "resend_cooldown"
    assert respuesta.json()["retry_after_s"] > 0


async def test_tope_diario_es_409_resend_limit(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await escena(db_session, redis_client, settings)
    fila = await job(db_session, e.appointment, status=ReminderStatus.FAILED)
    for horas in (1, 2, 3):
        await reenvio(db_session, fila, e.recepcion, NOW - timedelta(hours=horas))

    respuesta = await app_client.post(resend_url(e.appointment.id), headers=e.headers["recepcion"])

    assert respuesta.status_code == 409
    assert respuesta.json() == {"detail": "resend_limit"}
    assert await resends_of(db_session, fila.id) == 3


async def test_el_tope_cuenta_el_dia_local_de_la_clinica(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    # NOW = 08:00 de Buenos Aires (11:00 UTC). 02:30 UTC es el mismo día UTC pero las 23:30 del
    # día local anterior: esos reenvíos no cuentan para el tope de hoy.
    e = await escena(db_session, redis_client, settings)
    fila = await job(db_session, e.appointment, status=ReminderStatus.FAILED)
    ayer_local = datetime(NOW.year, NOW.month, NOW.day, 2, 30, tzinfo=UTC)
    for minutos in (0, 5, 10):
        await reenvio(db_session, fila, e.recepcion, ayer_local + timedelta(minutes=minutos))

    respuesta = await app_client.post(resend_url(e.appointment.id), headers=e.headers["recepcion"])

    assert respuesta.status_code == 202, respuesta.text
    assert respuesta.json()["manual_resends_today"] == 1


async def test_dos_pedidos_concurrentes_dejan_un_solo_reenvio(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena_ = await commit_scene(rem_maker, opt_in=True, starts_in=timedelta(days=2))
    fila = await commit_job(rem_maker, escena_.appointment, status=ReminderStatus.FAILED)
    async with rem_maker() as session:
        usuario = await make_user(session, escena_.clinic, role=UserRole.RECEPCION)
        await session.commit()
    actor = Actor(
        clinic_id=escena_.clinic.id,
        type=ActorType.USER,
        user_id=usuario.id,
        roles=frozenset({UserRole.RECEPCION}),
    )

    async def _uno() -> ResendAccepted | DomainError:
        async with rem_maker() as session:
            try:
                return await resend(
                    session,
                    actor,
                    escena_.appointment.id,
                    "t_24h",
                    ReminderChannel.WHATSAPP,
                    None,
                    now=AHORA,
                    settings=settings,
                )
            except DomainError as error:
                return error

    resultados = await asyncio.gather(_uno(), _uno())

    aceptados = [r for r in resultados if isinstance(r, ResendAccepted)]
    rechazos = [r for r in resultados if isinstance(r, DomainError)]
    assert len(aceptados) == 1 and len(rechazos) == 1
    assert rechazos[0].detail == "resend_cooldown"
    assert rechazos[0].extra is not None and rechazos[0].extra["retry_after_s"] > 0
    async with rem_maker() as session:
        assert await resends_of(session, fila.id) == 1
