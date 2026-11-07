"""Efecto de un reenvío aceptado (C-11, D4; spec manual-actions).

El job se resetea a `scheduled` sin datos del envío anterior, se audita con actor y nota, la
request no envía nada y un estado tardío del mensaje anterior no lo toca. Datos ficticios
(regla 13).
"""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
from app.core.settings import Settings
from app.models import (
    DeliveryEvent,
    DeliveryEventType,
    ReminderJob,
    ReminderManualResend,
    ReminderReason,
    ReminderStatus,
)
from app.modules.notifications.payload import StatusEvent
from app.modules.notifications.statuses import apply_status
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import MutableClock
from tests.timeline_helpers import NOW, escena, evento, job, resend_url

pytestmark = pytest.mark.integration

ID_VIEJO = "wamid.REENVIO-VIEJO-FICTICIO"


async def _releer(db: AsyncSession, fila: ReminderJob) -> ReminderJob:
    releido = await db.scalar(
        select(ReminderJob)
        .where(ReminderJob.id == fila.id)
        .execution_options(populate_existing=True)
    )
    assert releido is not None
    return releido


async def _sent(db: AsyncSession, fila: ReminderJob) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(DeliveryEvent)
            .where(
                DeliveryEvent.reminder_job_id == fila.id,
                DeliveryEvent.event_type == DeliveryEventType.SENT,
            )
        )
        or 0
    )


async def test_el_202_resetea_el_job_y_audita(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await escena(db_session, redis_client, settings)
    fila = await job(
        db_session,
        e.appointment,
        status=ReminderStatus.FAILED,
        attempts=3,
        sent_at=NOW - timedelta(hours=2),
        provider_message_id=ID_VIEJO,
        cost_micros=12500,
        last_error="meta_131026",
        reason=ReminderReason.PROVIDER_REJECTED.value,
    )
    await evento(db_session, fila, DeliveryEventType.SENT, NOW - timedelta(hours=2))
    programado, snapshot = fila.scheduled_for, fila.starts_at_snapshot

    respuesta = await app_client.post(
        resend_url(e.appointment.id),
        json={"note": "Paciente pidió reenvío"},
        headers=e.headers["recepcion"],
    )

    assert respuesta.status_code == 202, respuesta.text
    j = await _releer(db_session, fila)
    assert j.status is ReminderStatus.SCHEDULED
    assert j.available_at == NOW and j.manual_resend_at == NOW
    assert j.attempts == 0 and j.claimed_at is None
    assert (j.sent_at, j.provider_message_id, j.cost_micros, j.last_error, j.reason) == (
        None,
        None,
        None,
        None,
        None,
    )
    assert (j.scheduled_for, j.starts_at_snapshot) == (programado, snapshot)
    [auditoria] = (
        await db_session.scalars(
            select(ReminderManualResend).where(ReminderManualResend.reminder_job_id == fila.id)
        )
    ).all()
    assert auditoria.actor_user_id == e.recepcion.id
    assert auditoria.note == "Paciente pidió reenvío"
    assert auditoria.clinic_id == e.staff.clinic.id
    # La request no envía: sigue habiendo un solo `sent` (el anterior).
    assert await _sent(db_session, fila) == 1


async def test_sin_nota_la_auditoria_queda_en_null(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await escena(db_session, redis_client, settings)
    fila = await job(db_session, e.appointment, status=ReminderStatus.FAILED)

    respuesta = await app_client.post(resend_url(e.appointment.id), headers=e.headers["admin"])

    assert respuesta.status_code == 202
    nota = await db_session.scalar(
        select(ReminderManualResend.note).where(ReminderManualResend.reminder_job_id == fila.id)
    )
    assert nota is None


async def test_un_estado_tardio_del_mensaje_anterior_no_cambia_el_job(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await escena(db_session, redis_client, settings)
    fila = await job(
        db_session,
        e.appointment,
        status=ReminderStatus.SENT,
        provider_message_id=ID_VIEJO,
    )
    await evento(db_session, fila, DeliveryEventType.SENT, NOW - timedelta(hours=1))
    assert (
        await app_client.post(resend_url(e.appointment.id), headers=e.headers["recepcion"])
    ).status_code == 202

    await apply_status(
        db_session,
        StatusEvent(id=ID_VIEJO, status="delivered", timestamp=str(int(NOW.timestamp()))),
        now=NOW,
    )

    j = await _releer(db_session, fila)
    assert j.status is ReminderStatus.SCHEDULED
    tipos = (
        await db_session.scalars(
            select(DeliveryEvent.event_type).where(DeliveryEvent.reminder_job_id == fila.id)
        )
    ).all()
    assert list(tipos) == [DeliveryEventType.SENT]
    timeline = (
        await app_client.get(
            f"/api/appointments/{e.appointment.id}/reminders", headers=e.headers["recepcion"]
        )
    ).json()
    [paso] = timeline["steps"]
    assert paso["status"] == "scheduled"
    assert [(ev["type"], ev["previous"]) for ev in paso["events"]] == [
        ("scheduled", False),
        ("sent", True),
        ("manual_resend", True),
    ]


async def test_un_skipped_por_consentimiento_se_reenvia_tras_el_opt_in(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await escena(db_session, redis_client, settings, opt_in=False)
    fila = await job(
        db_session,
        e.appointment,
        status=ReminderStatus.SKIPPED,
        reason=ReminderReason.NO_CONSENT.value,
    )
    url = resend_url(e.appointment.id)
    assert (await app_client.post(url, headers=e.headers["recepcion"])).status_code == 409

    opt_in = await app_client.put(
        f"/api/patients/{e.patient.id}/consent/whatsapp",
        json={"status": "opt_in"},
        headers=e.headers["recepcion"],
    )
    assert opt_in.status_code == 200, opt_in.text
    respuesta = await app_client.post(url, headers=e.headers["recepcion"])

    assert respuesta.status_code == 202, respuesta.text
    assert (await _releer(db_session, fila)).status is ReminderStatus.SCHEDULED
