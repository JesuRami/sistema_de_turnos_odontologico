"""Extremo a extremo de la lista de espera (C-12, tarea 11.2): Postgres y Redis reales, sin mocks
de DB, proveedor `fake`.

Dos pacientes se anotan por la página pública con opt-in → el titular cancela su turno por el link
de gestión → nace la oferta para la primera y su envío → el tick la envía por WhatsApp → vence sin
respuesta → rota a la segunda → el tick se la envía → la segunda toca "Tomarlo" (webhook firmado) →
turno `waitlist` confirmado con sus recordatorios → el reporte de conversión cuenta 2 creadas, 1
vencida y 1 aceptada, y el de WhatsApp 2 envíos del paso `waitlist_offer`. Datos ficticios.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, date, datetime, time, timedelta

import pytest
from app.common.clock import get_now
from app.core.settings import Settings, get_settings
from app.models import (
    Appointment,
    AppointmentOrigin,
    AppointmentStatus,
    ReminderChannel,
    ReminderJob,
    ReminderStatus,
    WaitlistOffer,
    WaitlistOfferStatus,
)
from app.modules.reminders.dispatch import run_tick
from app.modules.reminders.seeding import seed_default_templates
from app.modules.reminders.senders.fake import FakeSender
from app.modules.reports.service import ReportsService
from app.modules.reports.waitlist import waitlist_report
from app.modules.reports.whatsapp import whatsapp_report
from app.modules.waiting_list.engine import run_waitlist_tick
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.booking_helpers import client_for, committed_app, make_booking
from tests.conftest import AGENDA_NOW, MutableClock
from tests.factories import make_appointment, make_patient
from tests.reminder_helpers import dispatch_settings
from tests.whatsapp_helpers import (
    WEBHOOK,
    button_message,
    encode,
    envelope,
    signed_headers,
    whatsapp_settings,
)

pytestmark = pytest.mark.integration

W = ReminderChannel.WHATSAPP
HUECO = AGENDA_NOW + timedelta(days=2, hours=2)  # miércoles 09/01 10:00 local
TELEFONOS = ("011 15 5555-0131", "011 15 5555-0132")


async def _ofertas(maker: async_sessionmaker[AsyncSession]) -> list[WaitlistOffer]:
    async with maker() as s:
        return list(
            (await s.execute(select(WaitlistOffer).order_by(WaitlistOffer.created_at))).scalars()
        )


async def _wamid(maker: async_sessionmaker[AsyncSession], offer: WaitlistOffer) -> str:
    async with maker() as s:
        job = await s.scalar(select(ReminderJob).where(ReminderJob.waitlist_offer_id == offer.id))
    assert job is not None and job.status is ReminderStatus.SENT and job.provider_message_id
    return job.provider_message_id


async def test_hueco_cancelado_lista_de_espera_y_turno(
    rem_engine: AsyncEngine,
    rem_maker: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    settings: Settings,
) -> None:
    configuracion = whatsapp_settings(
        dispatch_settings(settings, REMINDER_COST_WHATSAPP_MICROS=12500)
    )
    token = secrets.token_urlsafe(32)
    async with rem_maker() as s:
        b = await make_booking(s, weekday=2, start_time=time(9), end_time=time(13))
        await seed_default_templates(s, b.clinic.id)
        titular = await make_patient(s, b.clinic, full_name="Titular Ficticio")
        await make_appointment(
            s,
            b.clinic,
            patient=titular,
            professional=b.professional,
            chair=b.chair,
            starts_at=HUECO,
            status=AppointmentStatus.PENDING,
            origin=AppointmentOrigin.ONLINE,
            manage_token_hash=hashlib.sha256(token.encode()).digest(),
        )
        await s.commit()
    reloj = MutableClock(current=AGENDA_NOW)
    app = committed_app(rem_engine, redis_client, configuracion)
    app.dependency_overrides[get_settings] = lambda: configuracion
    app.dependency_overrides[get_now] = lambda: reloj.current
    sender = FakeSender(W)

    async with client_for(app) as client:
        # 1. Dos pacientes se anotan por la página pública, en ese orden.
        for i, telefono in enumerate(TELEFONOS):
            r = await client.post(
                f"/api/booking/{b.slug}/waiting-list",
                json={
                    "professional_id": str(b.professional.id),
                    "date_from": "2030-01-07",
                    "date_to": "2030-01-20",
                    "patient": {
                        "full_name": f"Espera Ficticia {i}",
                        "phone": telefono,
                        "whatsapp_opt_in": True,
                        "privacy_accepted": True,
                    },
                },
            )
            assert r.status_code == 201, r.text
            reloj.advance(seconds=1)

        # 2. El titular cancela por su link: la oferta nace para la primera.
        r = await client.patch(f"/api/manage/{token}", json={"action": "cancel"})
        assert r.status_code == 200, r.text
        [primera] = await _ofertas(rem_maker)
        assert primera.status is WaitlistOfferStatus.PENDING

        # 3. El tick envía la oferta por WhatsApp con su link.
        await run_tick(rem_maker, {W: sender}, configuracion, now=reloj)
        assert [m.template_name for m in sender.sent] == ["hueco_lista_espera_v1"]
        assert "/o/w1." in sender.sent[0].params["link"]

        # 4. Vence sin respuesta y rota a la segunda; el tick se la envía.
        reloj.advance(hours=5)
        stats = await run_waitlist_tick(rem_maker, configuracion, now=reloj)
        assert (stats.expired_offers, stats.rotated) == (1, 1)
        vencida, segunda = await _ofertas(rem_maker)
        assert vencida.status is WaitlistOfferStatus.EXPIRED
        assert segunda.entry_id != vencida.entry_id
        await run_tick(rem_maker, {W: sender}, configuracion, now=reloj)
        assert len(sender.sent) == 2
        wamid = await _wamid(rem_maker, segunda)

        # 5. La segunda toca "Tomarlo" citando el mensaje (webhook firmado).
        mensaje = button_message(
            "5491155550132",
            "offer_accept",
            reloj.current,
            message_id="wamid.IN-" + secrets.token_hex(6),
            context_id=wamid,
        )
        cuerpo = encode(envelope(messages=[mensaje]))
        r = await client.post(WEBHOOK, content=cuerpo, headers=signed_headers(cuerpo))
        assert r.status_code == 200, r.text

    # 6. Turno `waitlist` confirmado, con sus recordatorios programados.
    async with rem_maker() as s:
        turno = await s.scalar(
            select(Appointment).where(Appointment.origin == AppointmentOrigin.WAITLIST)
        )
        assert turno is not None
        assert turno.status is AppointmentStatus.CONFIRMED
        assert (turno.starts_at, turno.professional_id) == (HUECO, b.professional.id)
        recordatorios = list(
            (
                await s.execute(select(ReminderJob).where(ReminderJob.appointment_id == turno.id))
            ).scalars()
        )
        assert recordatorios

        # 7. Reportes. La conversión se cuenta por la hora real de los eventos (`clock_timestamp()`
        # de la base); el envío, por el `sent` del motor, que usa el reloj simulado de 2030.
        hoy = datetime.now(UTC).date()
        reales = await ReportsService(s, b.clinic.id).window(
            hoy - timedelta(days=1), hoy + timedelta(days=1)
        )
        conversion = await waitlist_report(s, b.clinic.id, reales)
        ventana = await ReportsService(s, b.clinic.id).window(date(2030, 1, 1), date(2030, 1, 31))
        assert (
            conversion.totals.created,
            conversion.totals.expired,
            conversion.totals.accepted,
        ) == (2, 1, 1)
        assert conversion.totals.conversion_pct == 50.0
        mensajes = await whatsapp_report(s, b.clinic.id, ventana)
    fila = next(r for r in mensajes.rows if (r.step, r.channel) == ("waitlist_offer", W))
    assert fila.sent == 2
    assert fila.cost_usd == "0.025000"
