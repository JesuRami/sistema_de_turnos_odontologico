"""Envío de ofertas de la lista de espera por el motor de recordatorios (C-12, D2).

Spec `waitlist/offer-delivery`. Postgres real con commits (sesiones del worker), sender `fake`.
Datos ficticios (regla 13).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from app.core.settings import Settings
from app.models import (
    NotificationTemplate,
    ReminderChannel,
    ReminderJob,
    ReminderStatus,
    WaitlistOffer,
    WaitlistOfferStatus,
)
from app.modules.reminders.dispatch import TickStats, _claim_batch, _deliver, run_tick
from app.modules.reminders.senders.base import SendError
from app.modules.reminders.senders.fake import FakeSender
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.reminder_helpers import (
    AHORA,
    commit_job,
    commit_scene,
    dispatch_settings,
    email_ficticio,
    read_jobs,
)
from tests.waitlist_helpers import OfferScene, commit_offer_scene

pytestmark = pytest.mark.integration

W = ReminderChannel.WHATSAPP
E = ReminderChannel.EMAIL


def _senders() -> dict[ReminderChannel, FakeSender]:
    return {W: FakeSender(W), E: FakeSender(E)}


async def _tick(
    maker: async_sessionmaker[AsyncSession],
    senders: dict[ReminderChannel, FakeSender],
    settings: Settings,
    **cambios: object,
) -> TickStats:
    return await run_tick(maker, senders, dispatch_settings(settings, **cambios), now=lambda: AHORA)


async def _jobs(maker: async_sessionmaker[AsyncSession], o: OfferScene) -> list[ReminderJob]:
    async with maker() as s:
        return list(
            (
                await s.execute(
                    select(ReminderJob)
                    .where(ReminderJob.waitlist_offer_id == o.offer.id)
                    .order_by(ReminderJob.channel)
                )
            ).scalars()
        )


async def test_la_oferta_sale_con_su_plantilla_y_su_link(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    o = await commit_offer_scene(rem_maker, now=AHORA)
    senders = _senders()

    await _tick(rem_maker, senders, settings)

    [job] = await _jobs(rem_maker, o)
    assert job.status is ReminderStatus.SENT
    assert job.cost_micros is not None
    [mensaje] = senders[W].sent
    assert mensaje.template_name == "hueco_lista_espera_v1"
    assert set(mensaje.params) == {
        "nombre",
        "clinica",
        "fecha",
        "hora",
        "profesional",
        "vence",
        "link",
    }
    assert mensaje.params["profesional"] == "Dra. Ficticia Oferta"
    # 12:00 UTC = 09:00 en Buenos Aires.
    assert mensaje.params["vence"] == "09:00"
    assert "/o/w1." in mensaje.params["link"]
    assert "/g/" not in mensaje.params["link"]
    assert mensaje.buttons == ("offer_accept", "offer_decline")


@pytest.mark.parametrize("estado", [WaitlistOfferStatus.CANCELLED, WaitlistOfferStatus.DECLINED])
async def test_oferta_cerrada_antes_del_reclamo(
    rem_maker: async_sessionmaker[AsyncSession],
    settings: Settings,
    estado: WaitlistOfferStatus,
) -> None:
    o = await commit_offer_scene(rem_maker, now=AHORA, offer_status=estado)
    senders = _senders()

    await _tick(rem_maker, senders, settings)

    [job] = await _jobs(rem_maker, o)
    assert job.status is ReminderStatus.CANCELLED
    assert job.reason == "offer_closed"
    assert senders[W].sent == []


async def test_oferta_vencida_en_la_cola(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    o = await commit_offer_scene(rem_maker, now=AHORA, expires_in=timedelta(minutes=-5))
    senders = _senders()

    await _tick(rem_maker, senders, settings)

    [job] = await _jobs(rem_maker, o)
    assert job.status is ReminderStatus.CANCELLED
    assert job.reason == "offer_closed"


async def test_oferta_cerrada_entre_el_reclamo_y_el_envio(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    o = await commit_offer_scene(rem_maker, now=AHORA)
    config = dispatch_settings(settings)
    senders = _senders()
    stats = TickStats()
    lote = await _claim_batch(rem_maker, [W, E], AHORA, config, stats)
    [listo] = lote.ready
    async with rem_maker() as s:
        await s.execute(
            update(WaitlistOffer)
            .where(WaitlistOffer.id == o.offer.id)
            .values(status=WaitlistOfferStatus.CANCELLED, closed_reason="test")
        )
        await s.commit()

    await _deliver(rem_maker, senders, config, lambda: AHORA, listo, stats, asyncio.Semaphore(1))

    [job] = await _jobs(rem_maker, o)
    assert job.status is ReminderStatus.CANCELLED
    assert job.reason == "offer_closed"
    assert senders[W].sent == []


async def test_sin_opt_in_no_sale_por_whatsapp(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    o = await commit_offer_scene(rem_maker, now=AHORA, opt_in=False)
    senders = _senders()

    await _tick(rem_maker, senders, settings)

    [job] = await _jobs(rem_maker, o)
    assert job.status is ReminderStatus.SKIPPED
    assert job.reason == "no_consent"


async def test_plantilla_inactiva(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    o = await commit_offer_scene(rem_maker, now=AHORA)
    async with rem_maker() as s:
        await s.execute(
            update(NotificationTemplate)
            .where(
                NotificationTemplate.clinic_id == o.scene.clinic.id,
                NotificationTemplate.step == "waitlist_offer",
            )
            .values(active=False)
        )
        await s.commit()
    senders = _senders()

    await _tick(rem_maker, senders, settings)

    [job] = await _jobs(rem_maker, o)
    assert job.status is ReminderStatus.FAILED
    assert job.reason == "template_inactive"
    assert senders[W].sent == []


async def test_fallo_definitivo_escala_a_email_de_la_misma_oferta(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    o = await commit_offer_scene(rem_maker, now=AHORA, email=email_ficticio())
    senders = _senders()
    senders[W].failures = [SendError("rejected", retryable=False)]

    await _tick(rem_maker, senders, settings)
    await _tick(rem_maker, senders, settings)

    jobs = await _jobs(rem_maker, o)
    por_canal = {j.channel: j for j in jobs}
    assert por_canal[W].status is ReminderStatus.FAILED
    assert por_canal[E].status is ReminderStatus.SENT
    assert por_canal[E].appointment_id is None
    [mensaje] = senders[E].sent
    assert "/o/w1." in mensaje.params["link"]


async def test_los_jobs_de_turnos_siguen_igual_en_el_mismo_tick(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    o = await commit_offer_scene(rem_maker, now=AHORA)
    escena = await commit_scene(rem_maker, opt_in=True)
    await commit_job(rem_maker, escena.appointment, scheduled_for=AHORA - timedelta(minutes=1))
    senders = _senders()

    await _tick(rem_maker, senders, settings)

    [oferta] = await _jobs(rem_maker, o)
    turno = await read_jobs(rem_maker, escena.appointment.id)
    assert oferta.status is ReminderStatus.SENT
    assert turno[("t_24h", "whatsapp")].status is ReminderStatus.SENT
    assert sorted(m.template_name for m in senders[W].sent) == [
        "hueco_lista_espera_v1",
        "recordatorio_24h_v1",
    ]
