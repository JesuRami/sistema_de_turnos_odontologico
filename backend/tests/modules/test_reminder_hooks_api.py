"""La secuencia de jobs sigue a toda mutación del turno, por cualquier camino (C-09, D3).

Recepción, reserva pública, bloqueo de agenda y gestión por token pasan por las tres funciones
de escritura de C-05 (`book`, `_reschedule`, `apply_transition`), que reconcilian en su misma
transacción. Reloj fijo: lunes 2030-01-07 08:00 Buenos Aires.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import httpx
import pytest
from app.core.settings import Settings
from app.models import AppointmentOrigin, AppointmentStatus, ReminderJob
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.appointment_helpers import at, iso, make_agenda, post, reload, seed
from tests.booking_helpers import client_for, committed_app, make_booking, reserva
from tests.conftest import AGENDA_NOW, MutableClock
from tests.manage_helpers import make_managed
from tests.reminder_helpers import jobs_of, statuses_of

pytestmark = pytest.mark.integration

CUATRO_PENDIENTES = {
    "created/whatsapp": "scheduled",
    "t_72h/whatsapp": "scheduled",
    "t_24h/whatsapp": "scheduled",
    "t_3h/whatsapp": "scheduled",
}


async def _total_jobs(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count()).select_from(ReminderJob)) or 0)


async def _programar(session: AsyncSession, managed_id: uuid.UUID) -> None:
    """Programa los jobs de un turno sembrado directo (sin pasar por `book`)."""
    from app.modules.reminders.scheduling import schedule_new

    turno = await reload(session, managed_id)
    await schedule_new(session, turno, now=AGENDA_NOW)


# ------------------------------------------------------------------------- alta


async def test_crear_un_turno_por_recepcion_programa_alta_y_tres_pasos(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)

    response = await post(app_client, agenda, at(10, days=7))

    assert response.status_code == 201, response.text
    turno_id = uuid.UUID(response.json()["id"])
    assert await statuses_of(db_session, turno_id) == CUATRO_PENDIENTES
    jobs = await jobs_of(db_session, turno_id)
    assert jobs[("created", "whatsapp")].scheduled_for == AGENDA_NOW
    assert jobs[("t_24h", "whatsapp")].scheduled_for == at(10, days=7) - timedelta(hours=24)


async def test_la_reserva_publica_programa_la_secuencia_en_la_misma_transaccion(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)

    response = await app_client.post(
        f"/api/booking/{b.slug}/appointments", json=reserva(b, iso(10, days=7))
    )

    assert response.status_code == 201, response.text
    [turno_id] = {
        j.appointment_id for j in (await db_session.execute(select(ReminderJob))).scalars()
    }
    assert await statuses_of(db_session, turno_id) == CUATRO_PENDIENTES


async def test_un_409_por_solapamiento_no_deja_jobs(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    primero = await post(app_client, agenda, at(10, days=7))
    assert primero.status_code == 201, primero.text
    antes = await _total_jobs(db_session)

    segundo = await post(app_client, agenda, at(10, days=7))

    assert segundo.status_code == 409
    assert await _total_jobs(db_session) == antes == 4


# ------------------------------------------------------------------ reprogramar


async def test_reprogramar_por_recepcion_recalcula_los_pendientes(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await seed(db_session, agenda, at(10, days=7))
    await _programar(db_session, turno.id)

    response = await app_client.patch(
        f"/api/appointments/{turno.id}",
        json={"starts_at": iso(11, days=14)},
        headers=agenda.headers["recepcion"],
    )

    assert response.status_code == 200, response.text
    jobs = await jobs_of(db_session, turno.id)
    for paso, horas in (("t_72h", 72), ("t_24h", 24), ("t_3h", 3)):
        assert jobs[(paso, "whatsapp")].scheduled_for == at(11, days=14) - timedelta(hours=horas)


async def test_reprogramar_por_token_recalcula_los_pendientes(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    managed = await make_managed(db_session, at(10, days=7))
    await _programar(db_session, managed.appointment.id)

    response = await app_client.patch(
        managed.url, json={"action": "reschedule", "starts_at": iso(11, days=7)}
    )

    assert response.status_code == 200, response.text
    jobs = await jobs_of(db_session, managed.appointment.id)
    assert jobs[("t_24h", "whatsapp")].scheduled_for == at(11, days=7) - timedelta(hours=24)
    assert {j.starts_at_snapshot for j in jobs.values()} == {at(11, days=7)}


# --------------------------------------------------------------------- cancelar


async def test_cancelar_por_recepcion_cancela_los_pendientes(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await seed(db_session, agenda, at(10, days=7))
    await _programar(db_session, turno.id)

    response = await app_client.post(
        f"/api/appointments/{turno.id}/transitions",
        json={"to": "cancelled", "reason": "paciente"},
        headers=agenda.headers["recepcion"],
    )

    assert response.status_code == 200, response.text
    assert set((await statuses_of(db_session, turno.id)).values()) == {"cancelled"}


async def test_cancelar_por_bloqueo_de_agenda_cancela_los_pendientes(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await seed(db_session, agenda, at(10, days=7), status=AppointmentStatus.CONFIRMED)
    turno_id = turno.id
    profesional_id = agenda.staff.professional.id
    cabeceras = agenda.headers["admin"]
    await _programar(db_session, turno_id)

    response = await app_client.post(
        "/api/blocks",
        json={
            "professional_id": str(profesional_id),
            "starts_at": at(9, days=7).isoformat(),
            "ends_at": at(13, days=7).isoformat(),
            "reason": "vacaciones",
            "cancel_appointments": [{"appointment_id": str(turno_id), "reason": "bloqueo"}],
        },
        headers=cabeceras,
    )

    assert response.status_code == 201, response.text
    assert set((await statuses_of(db_session, turno_id)).values()) == {"cancelled"}


async def test_cancelar_por_token_cancela_los_pendientes_antes_del_commit(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    managed = await make_managed(db_session, at(10, days=7))
    await _programar(db_session, managed.appointment.id)

    response = await app_client.patch(managed.url, json={"action": "cancel", "reason": "viaje"})

    assert response.status_code == 200, response.text
    assert set((await statuses_of(db_session, managed.appointment.id)).values()) == {"cancelled"}


# ---------------------------------------------------------------------- confirmar


async def test_confirmar_por_token_cancela_72_y_24_y_conserva_3(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    managed = await make_managed(db_session, at(10, days=7))
    await _programar(db_session, managed.appointment.id)

    response = await app_client.patch(managed.url, json={"action": "confirm"})

    assert response.status_code == 200, response.text
    assert await statuses_of(db_session, managed.appointment.id) == {
        "created/whatsapp": "cancelled",
        "t_72h/whatsapp": "cancelled",
        "t_24h/whatsapp": "cancelled",
        "t_3h/whatsapp": "scheduled",
    }


async def test_confirmar_por_recepcion_un_turno_online_aplica_la_misma_regla(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await seed(
        db_session,
        agenda,
        at(10, days=7),
        status=AppointmentStatus.PENDING,
        origin=AppointmentOrigin.ONLINE,
    )
    await _programar(db_session, turno.id)

    response = await app_client.post(
        f"/api/appointments/{turno.id}/transitions",
        json={"to": "confirmed"},
        headers=agenda.headers["recepcion"],
    )

    assert response.status_code == 200, response.text
    assert await statuses_of(db_session, turno.id) == {
        "created/whatsapp": "cancelled",
        "t_72h/whatsapp": "cancelled",
        "t_24h/whatsapp": "cancelled",
        "t_3h/whatsapp": "scheduled",
    }


# -------------------------------------------------------------------- atomicidad


async def test_si_reconcile_falla_la_cancelacion_se_revierte(
    committed_engine: AsyncEngine,
    redis_client: Redis,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Transacciones reales: la request que falla en `reconcile` no deja nada a medias."""
    async with AsyncSession(committed_engine, expire_on_commit=False) as session:
        managed = await make_managed(session, at(10, days=7))
        await _programar(session, managed.appointment.id)
        await session.commit()
    turno_id = managed.appointment.id
    app = committed_app(committed_engine, redis_client, settings)

    async def _falla(*_: object, **__: object) -> None:
        raise RuntimeError("programación caída (simulada)")

    monkeypatch.setattr("app.modules.appointments.states.reconcile", _falla)

    async with client_for(app) as client:
        with pytest.raises(RuntimeError):
            await client.patch(managed.url, json={"action": "cancel", "reason": "viaje"})

    async with AsyncSession(committed_engine) as session:
        assert (await reload(session, turno_id)).status is AppointmentStatus.PENDING
        assert await statuses_of(session, turno_id) == CUATRO_PENDIENTES
