"""Extremo a extremo del motor (C-09, tarea 10.1): Postgres y Redis reales, sin mocks de DB.

Reserva online con opt-in → el worker envía el alta y el aviso de 72 h (proveedor `fake`) → el
paciente abre el link firmado QUE VIENE EN EL MENSAJE y confirma → los pasos que piden confirmar
se cancelan, el de 3 h sale. Es el único test que recorre todas las piezas juntas.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta

import pytest
from app.core.settings import Settings, get_settings
from app.models import ReminderChannel, ReminderJob
from app.modules.reminders.dispatch import run_tick
from app.modules.reminders.seeding import seed_default_templates
from app.modules.reminders.senders.fake import FakeSender
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.appointment_helpers import at, iso
from tests.booking_helpers import client_for, committed_app, make_booking, reserva
from tests.conftest import AGENDA_NOW, MutableClock
from tests.reminder_helpers import dispatch_settings, read_jobs

pytestmark = pytest.mark.integration

W = ReminderChannel.WHATSAPP


def _estados(jobs: Mapping[tuple[str, str], ReminderJob]) -> dict[str, str]:
    return {f"{paso}/{canal}": job.status.value for (paso, canal), job in jobs.items()}


async def test_reserva_online_recordatorios_confirmacion_por_el_link_del_mensaje(
    rem_engine: object,
    rem_maker: async_sessionmaker[AsyncSession],
    redis_client: Redis,
    settings: Settings,
) -> None:
    configuracion = dispatch_settings(settings)
    async with rem_maker() as session:
        b = await make_booking(session)
        await seed_default_templates(session, b.clinic.id)
        await session.commit()
    app = committed_app(rem_engine, redis_client, configuracion)  # type: ignore[arg-type]
    app.dependency_overrides[get_settings] = lambda: configuracion
    sender = FakeSender(W)
    reloj = MutableClock(current=AGENDA_NOW)
    inicio = at(10, days=7)

    # 1. Reserva pública con consentimiento de WhatsApp.
    async with client_for(app) as client:
        reservado = await client.post(
            f"/api/booking/{b.slug}/appointments", json=reserva(b, iso(10, days=7))
        )
        assert reservado.status_code == 201, reservado.text

        async with rem_maker() as session:
            from app.models import Appointment
            from sqlalchemy import select

            turno_id = (await session.execute(select(Appointment.id))).scalar_one()
        assert _estados(await read_jobs(rem_maker, turno_id)) == {
            "created/whatsapp": "scheduled",
            "t_72h/whatsapp": "scheduled",
            "t_24h/whatsapp": "scheduled",
            "t_3h/whatsapp": "scheduled",
        }

        # 2. El worker envía el alta ahora y el aviso de 72 h cuando llega su hora.
        await run_tick(rem_maker, {W: sender}, configuracion, now=reloj)
        reloj.current = inicio - timedelta(hours=72)
        await run_tick(rem_maker, {W: sender}, configuracion, now=reloj)
        assert [m.template_name for m in sender.sent] == ["turno_creado_v1", "recordatorio_72h_v1"]

        # 3. El paciente abre el link del mensaje (token firmado) y confirma.
        link = sender.sent[1].params["link"]
        assert "/g/v1." in link
        token = link.rsplit("/g/", 1)[1]
        vista = await client.get(f"/api/manage/{token}")
        assert vista.status_code == 200, vista.text
        assert vista.json()["actions"]["can_confirm"] is True
        confirmado = await client.patch(f"/api/manage/{token}", json={"action": "confirm"})
        assert confirmado.status_code == 200, confirmado.text

    # 4. Confirmar canceló los pasos que piden confirmar; el de 3 h sigue.
    assert _estados(await read_jobs(rem_maker, turno_id)) == {
        "created/whatsapp": "sent",
        "t_72h/whatsapp": "sent",
        "t_24h/whatsapp": "cancelled",
        "t_3h/whatsapp": "scheduled",
    }
    reloj.current = inicio - timedelta(hours=24)
    await run_tick(rem_maker, {W: sender}, configuracion, now=reloj)
    assert len(sender.sent) == 2  # el de 24 h ya no sale
    reloj.current = inicio - timedelta(hours=3)
    await run_tick(rem_maker, {W: sender}, configuracion, now=reloj)

    assert [m.template_name for m in sender.sent] == [
        "turno_creado_v1",
        "recordatorio_72h_v1",
        "recordatorio_3h_v1",
    ]
    assert _estados(await read_jobs(rem_maker, turno_id))["t_3h/whatsapp"] == "sent"
    # El link de 3 h es el mismo: un solo link estable por turno.
    assert sender.sent[2].params["link"] == link
