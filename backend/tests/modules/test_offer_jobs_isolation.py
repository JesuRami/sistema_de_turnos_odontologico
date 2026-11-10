"""Los envíos de oferta no se mezclan con los recordatorios de un turno (C-12, D2).

Spec `waitlist/offer-delivery` («no se mezclan»): timeline, seguimiento y recálculo de un turno
ignoran el job de oferta; los estados de Meta lo avanzan igual que a un recordatorio. Postgres
real con commits. Datos ficticios (regla 13).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from app.core.settings import Settings
from app.models import (
    ActorType,
    Appointment,
    ReminderChannel,
    ReminderJob,
    ReminderStatus,
    UserRole,
)
from app.modules.appointments.audit import Actor
from app.modules.notifications.payload import StatusEvent
from app.modules.notifications.statuses import apply_status
from app.modules.reminders.followup import follow_up
from app.modules.reminders.scheduling import reconcile
from app.modules.reminders.timeline import build_timeline
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.factories import make_appointment
from tests.reminder_helpers import AHORA, dispatch_settings, email_ficticio
from tests.waitlist_helpers import OfferScene, commit_offer_scene

pytestmark = pytest.mark.integration


async def _turno_del_mismo_paciente(
    maker: async_sessionmaker[AsyncSession], o: OfferScene
) -> Appointment:
    async with maker() as s:
        turno = await make_appointment(
            s,
            o.scene.clinic,
            patient=o.scene.patient,
            professional=o.scene.professional,
            chair=o.scene.chair,
            starts_at=AHORA + timedelta(days=5),
        )
        await s.commit()
    return turno


async def _job(maker: async_sessionmaker[AsyncSession], o: OfferScene) -> ReminderJob:
    async with maker() as s:
        job = await s.scalar(select(ReminderJob).where(ReminderJob.id == o.job.id))
    assert job is not None
    return job


async def _enviado(maker: async_sessionmaker[AsyncSession], o: OfferScene, wamid: str) -> None:
    async with maker() as s:
        await s.execute(
            update(ReminderJob)
            .where(ReminderJob.id == o.job.id)
            .values(
                status=ReminderStatus.SENT,
                sent_at=AHORA,
                provider_message_id=wamid,
                cost_micros=1000,
            )
        )
        await s.commit()


async def test_timeline_y_seguimiento_no_muestran_la_oferta(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    o = await commit_offer_scene(rem_maker, now=AHORA)
    turno = await _turno_del_mismo_paciente(rem_maker, o)
    actor = Actor(
        clinic_id=o.scene.clinic.id,
        type=ActorType.USER,
        user_id=None,
        roles=frozenset({UserRole.ADMIN}),
    )

    async with rem_maker() as s:
        timeline = await build_timeline(
            s, actor, turno.id, now=AHORA, settings=dispatch_settings(settings)
        )
        seguimiento = await follow_up(
            s, o.scene.clinic.id, AHORA, AHORA + timedelta(days=10), None, 50, now=AHORA
        )

    assert all(paso.step != "waitlist_offer" for paso in timeline.steps)
    assert seguimiento.items == []


async def test_reconcile_de_otro_turno_no_toca_la_oferta(
    rem_maker: async_sessionmaker[AsyncSession],
) -> None:
    o = await commit_offer_scene(rem_maker, now=AHORA)
    turno = await _turno_del_mismo_paciente(rem_maker, o)

    async with rem_maker() as s:
        fila = await s.get(Appointment, turno.id)
        assert fila is not None
        fila.starts_at = AHORA + timedelta(days=6)
        fila.ends_at = fila.starts_at + timedelta(minutes=30)
        fila.occupied_until = fila.ends_at
        await s.flush()
        await reconcile(s, fila, now=AHORA)
        await s.commit()

    job = await _job(rem_maker, o)
    assert job.status is ReminderStatus.SCHEDULED
    assert job.reason is None


async def test_delivered_de_meta_avanza_el_job_de_oferta(
    rem_maker: async_sessionmaker[AsyncSession],
) -> None:
    o = await commit_offer_scene(rem_maker, now=AHORA)
    await _enviado(rem_maker, o, "wamid.FICTICIO-OFERTA-1")

    async with rem_maker() as s:
        await apply_status(
            s,
            StatusEvent(id="wamid.FICTICIO-OFERTA-1", status="delivered", timestamp="1894003200"),
            now=AHORA,
        )
        await s.commit()

    job = await _job(rem_maker, o)
    assert job.status is ReminderStatus.DELIVERED
    assert job.cost_micros == 1000


async def test_failed_de_meta_escala_la_oferta_a_email(
    rem_maker: async_sessionmaker[AsyncSession],
) -> None:
    o = await commit_offer_scene(rem_maker, now=AHORA, email=email_ficticio())
    await _enviado(rem_maker, o, "wamid.FICTICIO-OFERTA-2")

    async with rem_maker() as s:
        await apply_status(
            s,
            StatusEvent(id="wamid.FICTICIO-OFERTA-2", status="failed", timestamp="1894003200"),
            now=AHORA,
        )
        await s.commit()

    async with rem_maker() as s:
        jobs = {
            j.channel: j
            for j in (
                await s.execute(
                    select(ReminderJob).where(ReminderJob.waitlist_offer_id == o.offer.id)
                )
            ).scalars()
        }
    assert jobs[ReminderChannel.WHATSAPP].status is ReminderStatus.FAILED
    assert jobs[ReminderChannel.EMAIL].status is ReminderStatus.SCHEDULED
