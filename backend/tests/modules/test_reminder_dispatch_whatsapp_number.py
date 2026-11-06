"""Despacho de WhatsApp con número por clínica y costo en el evento (C-10, D4/D8/D10).

Postgres real y sender fake que captura los mensajes; datos ficticios (regla 13).
"""

from __future__ import annotations

import secrets
from datetime import timedelta

import pytest
from app.core.settings import Settings
from app.models import DeliveryEventType, ReminderChannel, WhatsAppInbound, WhatsAppIntent
from app.modules.reminders.dispatch import run_tick
from app.modules.reminders.senders.fake import FakeSender
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.reminder_helpers import (
    AHORA,
    commit_job,
    commit_scene,
    dispatch_settings,
    read_events,
)

pytestmark = pytest.mark.integration

VENCIDO = AHORA - timedelta(minutes=1)
COMPARTIDO = "100000000000009"


def _numero() -> str:
    return "1" + "".join(secrets.choice("0123456789") for _ in range(14))


async def _tick(
    maker: async_sessionmaker[AsyncSession], settings: Settings, sender: FakeSender
) -> None:
    await run_tick(
        maker,
        {ReminderChannel.WHATSAPP: sender},
        dispatch_settings(
            settings, META_PHONE_NUMBER_ID=COMPARTIDO, REMINDER_COST_WHATSAPP_MICROS=12500
        ),
        now=lambda: AHORA,
    )


async def test_clinica_con_numero_propio_envia_desde_ese_numero(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    propio = _numero()
    escena = await commit_scene(rem_maker, opt_in=True, whatsapp_phone_number_id=propio)
    await commit_job(rem_maker, escena.appointment, scheduled_for=VENCIDO)
    sender = FakeSender(ReminderChannel.WHATSAPP)

    await _tick(rem_maker, settings, sender)

    [mensaje] = sender.sent
    assert mensaje.sender_id == propio


async def test_clinica_sin_numero_propio_usa_el_compartido(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True)
    await commit_job(rem_maker, escena.appointment, scheduled_for=VENCIDO)
    sender = FakeSender(ReminderChannel.WHATSAPP)

    await _tick(rem_maker, settings, sender)

    [mensaje] = sender.sent
    assert mensaje.sender_id == COMPARTIDO


async def test_el_mensaje_lleva_orden_de_parametros_y_botones_del_paso(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True)
    await commit_job(rem_maker, escena.appointment, scheduled_for=VENCIDO, step="t_24h")
    sender = FakeSender(ReminderChannel.WHATSAPP)

    await _tick(rem_maker, settings, sender)

    [mensaje] = sender.sent
    assert mensaje.template_name == "recordatorio_24h_v1"
    assert mensaje.param_order == ("hora", "profesional", "clinica", "link")
    assert mensaje.buttons == ("confirm", "change")
    assert set(mensaje.param_order) <= set(mensaje.params)


async def test_el_evento_sent_lleva_el_costo(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True)
    job = await commit_job(rem_maker, escena.appointment, scheduled_for=VENCIDO)
    sender = FakeSender(ReminderChannel.WHATSAPP)

    await _tick(rem_maker, settings, sender)

    [enviado] = [
        e for e in await read_events(rem_maker, job.id) if e.event_type is DeliveryEventType.SENT
    ]
    assert enviado.payload["cost_micros"] == 12500


async def test_recordatorio_con_ventana_abierta_sigue_siendo_plantilla(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True)
    async with rem_maker() as session:
        session.add(
            WhatsAppInbound(
                clinic_id=escena.clinic.id,
                provider_message_id="wamid.FICTICIO-ENTRANTE",
                phone_number_id=COMPARTIDO,
                patient_id=escena.patient.id,
                intent=WhatsAppIntent.UNKNOWN,
                routed_by="phone",
                occurred_at=AHORA - timedelta(hours=2),
            )
        )
        await session.commit()
    await commit_job(rem_maker, escena.appointment, scheduled_for=VENCIDO, step="t_3h")
    sender = FakeSender(ReminderChannel.WHATSAPP)

    await _tick(rem_maker, settings, sender)

    assert len(sender.sent) == 1
    assert sender.texts == []
