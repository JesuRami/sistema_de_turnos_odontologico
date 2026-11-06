"""Extremo a extremo del canal WhatsApp (C-10, tarea 13.2): Postgres y Redis reales, sin mocks
de DB, proveedor `fake`.

Reserva online con opt-in → el worker envía `turno_creado_v1` → Meta informa `delivered` y `read`
(webhook firmado) → el paciente toca «Confirmar» citando ese mensaje → el turno queda
`confirmed`, los pasos que piden confirmar se cancelan → el siguiente tick le responde que quedó
confirmado → el reporte del mes muestra el envío leído.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from app.core.settings import Settings, get_settings
from app.models import Appointment, AppointmentStatus, ReminderChannel
from app.modules.reminders.dispatch import run_tick
from app.modules.reminders.seeding import seed_default_templates
from app.modules.reminders.senders.fake import FakeSender
from app.modules.reports.service import ReportsService
from app.modules.reports.whatsapp import whatsapp_report
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.appointment_helpers import iso
from tests.booking_helpers import client_for, committed_app, make_booking, reserva
from tests.conftest import AGENDA_NOW, MutableClock
from tests.reminder_helpers import dispatch_settings, read_jobs
from tests.whatsapp_helpers import (
    SHARED_NUMBER,
    WEBHOOK,
    button_message,
    encode,
    envelope,
    signed_headers,
    status,
    whatsapp_settings,
)

pytestmark = pytest.mark.integration

W = ReminderChannel.WHATSAPP


async def test_reserva_recordatorio_estados_si_por_whatsapp_respuesta_y_reporte(
    rem_engine: object,
    rem_maker: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    settings: Settings,
) -> None:
    configuracion = whatsapp_settings(
        dispatch_settings(settings, REMINDER_COST_WHATSAPP_MICROS=12500)
    )
    async with rem_maker() as session:
        b = await make_booking(session)
        await seed_default_templates(session, b.clinic.id)
        await session.commit()
    app = committed_app(rem_engine, redis_client, configuracion)  # type: ignore[arg-type]
    app.dependency_overrides[get_settings] = lambda: configuracion
    sender = FakeSender(W)
    reloj = MutableClock(current=AGENDA_NOW)

    async with client_for(app) as client:
        # 1. Reserva pública con consentimiento de WhatsApp.
        reservado = await client.post(
            f"/api/booking/{b.slug}/appointments", json=reserva(b, iso(10, days=7))
        )
        assert reservado.status_code == 201, reservado.text
        async with rem_maker() as session:
            turno_id = (await session.execute(select(Appointment.id))).scalar_one()

        # 2. El worker envía el alta de turno desde el número compartido.
        await run_tick(rem_maker, {W: sender}, configuracion, now=reloj)
        [alta] = sender.sent
        assert (alta.template_name, alta.sender_id) == ("turno_creado_v1", SHARED_NUMBER)
        assert alta.buttons == ("confirm", "change")
        wamid = (await read_jobs(rem_maker, turno_id))[("created", "whatsapp")].provider_message_id
        assert wamid is not None

        # 3. Meta informa entregado y leído.
        estados = encode(
            envelope(
                statuses=[
                    status(wamid, "delivered", AGENDA_NOW + timedelta(seconds=5)),
                    status(wamid, "read", AGENDA_NOW + timedelta(seconds=30)),
                ]
            )
        )
        respuesta = await client.post(WEBHOOK, content=estados, headers=signed_headers(estados))
        assert respuesta.status_code == 200, respuesta.text

        # 4. El paciente toca «Confirmar» citando el mensaje.
        assert alta.to.startswith("+")
        si = encode(
            envelope(
                messages=[
                    button_message(
                        alta.to.removeprefix("+"),
                        "confirm",
                        AGENDA_NOW + timedelta(minutes=1),
                        message_id="wamid.E2E-SI",
                        context_id=wamid,
                    )
                ]
            )
        )
        respuesta = await client.post(WEBHOOK, content=si, headers=signed_headers(si))
        assert respuesta.status_code == 200, respuesta.text

    async with rem_maker() as session:
        turno = await session.get(Appointment, turno_id)
        assert turno is not None and turno.status is AppointmentStatus.CONFIRMED
    jobs = await read_jobs(rem_maker, turno_id)
    assert {f"{p}/{c}": j.status.value for (p, c), j in jobs.items()} == {
        "created/whatsapp": "read",
        "t_72h/whatsapp": "cancelled",
        "t_24h/whatsapp": "cancelled",
        "t_3h/whatsapp": "scheduled",
    }

    # 5. El siguiente tick responde que quedó confirmado, como texto de sesión.
    reloj.current = AGENDA_NOW + timedelta(minutes=2)
    await run_tick(rem_maker, {W: sender}, configuracion, now=reloj)
    [(numero, destino, cuerpo)] = sender.texts
    assert (numero, destino) == (SHARED_NUMBER, alta.to)
    assert "confirmado" in cuerpo

    # 6. El reporte del período muestra el envío leído y su costo.
    async with rem_maker() as session:
        dia = AGENDA_NOW.date()
        servicio = ReportsService(session, b.clinic.id)
        informe = await whatsapp_report(
            session,
            b.clinic.id,
            await servicio.window(dia - timedelta(days=1), dia + timedelta(days=1)),
        )
    fila = next(r for r in informe.rows if r.step == "created" and r.channel is W)
    assert (fila.sent, fila.delivered, fila.read, fila.failed, fila.cost_usd) == (
        1,
        1,
        1,
        0,
        "0.012500",
    )
