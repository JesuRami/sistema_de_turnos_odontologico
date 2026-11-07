"""Extremo a extremo del timeline y el reenvío manual (C-11, tarea 10.2): Postgres y Redis
reales, sin mocks de DB, proveedor `fake`.

Turno online `pending` → el tick envía el paso de 24 h → Meta informa `delivered` y `read`
(webhook firmado) → el timeline muestra `read` → recepción reenvía ese paso → `202` → el worker lo
envía → el timeline muestra dos `sent` y el `manual_resend` → el reporte WhatsApp cuenta 2 enviados
con el costo de ambos.

Se reenvía el paso de 24 h (no el de 3 h del borrador de la tarea): a esa hora el de 3 h todavía no
se intentó y la guarda correcta es `409 reminder_pending`.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from app.common.clock import get_now
from app.core.settings import Settings, get_settings
from app.models import (
    AppointmentOrigin,
    AppointmentStatus,
    ReminderChannel,
    ReminderStatus,
)
from app.modules.reminders.dispatch import run_tick
from app.modules.reminders.seeding import seed_default_templates
from app.modules.reminders.senders.fake import FakeSender
from app.modules.reports.service import ReportsService
from app.modules.reports.whatsapp import whatsapp_report
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.agenda_helpers import make_staff
from tests.booking_helpers import client_for, committed_app
from tests.conftest import AGENDA_NOW, MutableClock
from tests.factories import make_appointment, make_patient
from tests.reminder_helpers import commit_job, dispatch_settings, read_jobs
from tests.whatsapp_helpers import (
    WEBHOOK,
    encode,
    envelope,
    signed_headers,
    status,
    whatsapp_settings,
)

pytestmark = pytest.mark.integration

W = ReminderChannel.WHATSAPP


async def test_timeline_reenvio_manual_y_reporte(
    rem_engine: object,
    rem_maker: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    settings: Settings,
) -> None:
    configuracion = whatsapp_settings(
        dispatch_settings(settings, REMINDER_COST_WHATSAPP_MICROS=12500)
    )
    async with rem_maker() as session:
        staff = await make_staff(session, redis_client, configuracion)
        paciente = await make_patient(session, staff.clinic, whatsapp_opt_in=True)
        turno = await make_appointment(
            session,
            staff.clinic,
            patient=paciente,
            professional=staff.professional,
            chair=staff.chair,
            starts_at=AGENDA_NOW + timedelta(hours=30),
            status=AppointmentStatus.PENDING,
            origin=AppointmentOrigin.ONLINE,
        )
        await seed_default_templates(session, staff.clinic.id)
        await session.commit()
    await commit_job(rem_maker, turno, step="t_24h")
    reloj = MutableClock(current=AGENDA_NOW + timedelta(hours=6))
    app = committed_app(rem_engine, redis_client, configuracion)  # type: ignore[arg-type]
    app.dependency_overrides[get_settings] = lambda: configuracion
    app.dependency_overrides[get_now] = lambda: reloj.current
    sender = FakeSender(W)
    recepcion = staff.headers["recepcion"]
    timeline = f"/api/appointments/{turno.id}/reminders"

    async with client_for(app) as client:
        # 1. El tick envía el paso de 24 h.
        await run_tick(rem_maker, {W: sender}, configuracion, now=reloj)
        wamid = (await read_jobs(rem_maker, turno.id))[("t_24h", "whatsapp")].provider_message_id
        assert len(sender.sent) == 1 and wamid is not None

        # 2. Meta informa entregado y leído (webhook firmado).
        estados = encode(
            envelope(
                statuses=[
                    status(wamid, "delivered", reloj.current + timedelta(seconds=5)),
                    status(wamid, "read", reloj.current + timedelta(seconds=30)),
                ]
            )
        )
        respuesta = await client.post(WEBHOOK, content=estados, headers=signed_headers(estados))
        assert respuesta.status_code == 200, respuesta.text

        # 3. El timeline muestra `read`.
        reloj.advance(minutes=10)
        [paso] = (await client.get(timeline, headers=recepcion)).json()["steps"]
        assert (paso["step"], paso["status"], paso["can_resend"]) == ("t_24h", "read", True)

        # 4. Recepción reenvía el paso: la request no envía.
        respuesta = await client.post(
            f"{timeline}/t_24h/whatsapp/resend",
            json={"note": "Pidió que se reenvíe"},
            headers=recepcion,
        )
        assert respuesta.status_code == 202, respuesta.text
        assert len(sender.sent) == 1
        job = (await read_jobs(rem_maker, turno.id))[("t_24h", "whatsapp")]
        assert job.status is ReminderStatus.SCHEDULED and job.provider_message_id is None

        # 5. El worker lo envía en el siguiente tick.
        reloj.advance(seconds=30)
        await run_tick(rem_maker, {W: sender}, configuracion, now=reloj)
        assert len(sender.sent) == 2

        # 6. El timeline muestra los dos envíos y el reenvío de recepción.
        [paso] = (await client.get(timeline, headers=recepcion)).json()["steps"]
        tipos = [(e["type"], e["previous"]) for e in paso["events"]]
        assert paso["status"] == "sent"
        assert tipos == [
            ("sent", True),
            ("delivered", True),
            ("read", True),
            ("manual_resend", True),
            ("sent", False),
        ]
        assert paso["events"][-1]["detail"]["manual"] is True
        assert paso["events"][3]["detail"] == {"actor_role": "recepcion"}
        assert "Pidió que se reenvíe" not in str(paso)

    # 7. El reporte cuenta los dos envíos y el costo de ambos.
    async with rem_maker() as session:
        dia = reloj.current.date()
        informe = await whatsapp_report(
            session,
            staff.clinic.id,
            await ReportsService(session, staff.clinic.id).window(
                dia - timedelta(days=1), dia + timedelta(days=1)
            ),
        )
    fila = next(r for r in informe.rows if r.step == "t_24h" and r.channel is W)
    assert (fila.sent, fila.delivered, fila.read, fila.failed, fila.cost_usd) == (
        2,
        1,
        1,
        0,
        "0.025000",
    )
