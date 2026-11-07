"""Guardas del reenvío manual (C-11, D4; spec manual-actions).

Postgres y Redis reales. Cada rechazo deja el job intacto y no crea auditoría. Datos ficticios
(regla 13).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import httpx
import pytest
from app.core.settings import Settings
from app.models import (
    AppointmentOrigin,
    AppointmentStatus,
    CancellationReason,
    Clinic,
    ReminderJob,
    ReminderStatus,
)
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import MutableClock
from tests.timeline_helpers import (
    NOW,
    E,
    Escena,
    escena,
    job,
    resend_url,
    resends_of,
)

pytestmark = pytest.mark.integration


async def _post(
    client: httpx.AsyncClient,
    e: Escena,
    rol: str = "recepcion",
    step: str = "t_24h",
    channel: str = "whatsapp",
    **cuerpo: Any,
) -> httpx.Response:
    return await client.post(
        resend_url(e.appointment.id, step, channel), json=cuerpo or None, headers=e.headers[rol]
    )


async def _status(db: AsyncSession, fila: ReminderJob) -> ReminderStatus:
    estado = await db.scalar(
        select(ReminderJob.status)
        .where(ReminderJob.id == fila.id)
        .execution_options(populate_existing=True)
    )
    assert estado is not None
    return estado


async def _rechazo(
    client: httpx.AsyncClient,
    db: AsyncSession,
    e: Escena,
    fila: ReminderJob,
    codigo: int,
    detalle: str,
    **kwargs: Any,
) -> None:
    antes = await _status(db, fila)
    respuesta = await _post(client, e, **kwargs)
    assert respuesta.status_code == codigo, respuesta.text
    assert respuesta.json()["detail"] == detalle
    assert await _status(db, fila) is antes
    assert await resends_of(db, fila.id) == 0


async def test_recepcion_reenvia_un_fallido(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await escena(db_session, redis_client, settings)
    fila = await job(db_session, e.appointment, status=ReminderStatus.FAILED)

    respuesta = await _post(app_client, e)

    assert respuesta.status_code == 202, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["job_id"] == str(fila.id)
    assert cuerpo["status"] == "scheduled"
    assert cuerpo["manual_resends_today"] == 1


async def test_odontologo_recibe_403(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await escena(db_session, redis_client, settings)
    fila = await job(db_session, e.appointment, status=ReminderStatus.FAILED)

    await _rechazo(app_client, db_session, e, fila, 403, "forbidden_role", rol="odontologo")


async def test_turno_de_otra_clinica_es_404(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    a = await escena(db_session, redis_client, settings)
    b = await escena(db_session, redis_client, settings)
    fila = await job(db_session, b.appointment, status=ReminderStatus.FAILED)

    respuesta = await app_client.post(resend_url(b.appointment.id), headers=a.headers["recepcion"])

    assert respuesta.status_code == 404
    assert respuesta.json() == {"detail": "not_found"}
    assert await resends_of(db_session, fila.id) == 0


async def test_sin_sesion_es_401(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await escena(db_session, redis_client, settings)

    assert (await app_client.post(resend_url(e.appointment.id))).status_code == 401


async def test_turno_cancelado_es_409_appointment_inactive(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await escena(db_session, redis_client, settings)
    fila = await job(db_session, e.appointment, status=ReminderStatus.FAILED)
    e.appointment.status = AppointmentStatus.CANCELLED
    e.appointment.cancelled_at = NOW
    e.appointment.cancellation_reason = CancellationReason.PACIENTE
    await db_session.flush()

    await _rechazo(app_client, db_session, e, fila, 409, "appointment_inactive")


async def test_turno_iniciado_es_409_appointment_started(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await escena(db_session, redis_client, settings, starts_in=-timedelta(minutes=10))
    fila = await job(db_session, e.appointment, status=ReminderStatus.FAILED)

    await _rechazo(app_client, db_session, e, fila, 409, "appointment_started")


async def test_job_inexistente_es_404_reminder_not_found(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await escena(db_session, redis_client, settings)

    respuesta = await _post(app_client, e, step="t_48h")

    assert respuesta.status_code == 404
    assert respuesta.json()["detail"] == "reminder_not_found"


async def test_paso_no_configurado_es_409_step_not_applicable(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await escena(db_session, redis_client, settings)
    fila = await job(db_session, e.appointment, status=ReminderStatus.FAILED)
    await db_session.execute(
        update(Clinic)
        .where(Clinic.id == e.staff.clinic.id)
        .values(reminder_steps=[{"offset_h": 3, "channel": "whatsapp"}])
    )

    await _rechazo(app_client, db_session, e, fila, 409, "step_not_applicable")


async def test_job_cancelado_es_409_step_not_applicable(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await escena(db_session, redis_client, settings)
    fila = await job(db_session, e.appointment, status=ReminderStatus.CANCELLED)

    await _rechazo(app_client, db_session, e, fila, 409, "step_not_applicable")


async def test_paso_de_confirmacion_de_un_online_confirmado_es_409(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await escena(
        db_session,
        redis_client,
        settings,
        origin=AppointmentOrigin.ONLINE,
        status=AppointmentStatus.CONFIRMED,
    )
    fila = await job(db_session, e.appointment, status=ReminderStatus.SENT)

    await _rechazo(app_client, db_session, e, fila, 409, "step_not_applicable")


async def test_job_programado_ordinario_es_409_reminder_pending(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await escena(db_session, redis_client, settings)
    fila = await job(db_session, e.appointment, status=ReminderStatus.SCHEDULED)

    await _rechazo(app_client, db_session, e, fila, 409, "reminder_pending")


async def test_job_en_vuelo_es_409_reminder_in_flight(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await escena(db_session, redis_client, settings)
    fila = await job(db_session, e.appointment, status=ReminderStatus.SENDING, attempts=1)

    await _rechazo(app_client, db_session, e, fila, 409, "reminder_in_flight")


async def test_sin_opt_in_es_409_no_consent(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await escena(db_session, redis_client, settings, opt_in=False)
    fila = await job(db_session, e.appointment, status=ReminderStatus.FAILED)

    await _rechazo(app_client, db_session, e, fila, 409, "no_consent")


async def test_email_sin_direccion_es_409_no_recipient(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await escena(db_session, redis_client, settings, email=None)
    fila = await job(db_session, e.appointment, channel=E, status=ReminderStatus.FAILED)

    await _rechazo(app_client, db_session, e, fila, 409, "no_recipient", channel="email")


@pytest.mark.parametrize(
    "nota",
    ["Llamar al +54 11 5555-0101", "DNI 30.123.456", "escribir a paciente.ficticio@example.com"],
)
async def test_nota_con_datos_personales_es_422_sin_fila(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
    nota: str,
) -> None:
    e = await escena(db_session, redis_client, settings)
    fila = await job(db_session, e.appointment, status=ReminderStatus.FAILED)

    respuesta = await _post(app_client, e, note=nota)

    assert respuesta.status_code == 422
    assert respuesta.json() == {"detail": "invalid_note"}
    assert nota not in respuesta.text
    assert await resends_of(db_session, fila.id) == 0


async def test_nota_de_mas_de_200_es_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await escena(db_session, redis_client, settings)
    await job(db_session, e.appointment, status=ReminderStatus.FAILED)

    respuesta = await _post(app_client, e, note="x" * 201)

    assert respuesta.status_code == 422
    assert respuesta.json() == {"detail": "invalid_note"}


async def test_campo_desconocido_en_el_cuerpo_es_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await escena(db_session, redis_client, settings)
    await job(db_session, e.appointment, status=ReminderStatus.FAILED)

    respuesta = await _post(app_client, e, note="ok", channel_override="email")

    assert respuesta.status_code == 422
