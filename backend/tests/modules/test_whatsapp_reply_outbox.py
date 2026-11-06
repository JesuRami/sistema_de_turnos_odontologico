"""Outbox de respuestas de sesión de WhatsApp en el worker (C-10, D8; RN-WA-03).

Postgres real con commits (como el despacho de C-09) y sender fake; datos ficticios (regla 13).
"""

from __future__ import annotations

import asyncio
import secrets
from datetime import datetime, timedelta
from typing import Any

import pytest
from app.core.settings import Settings
from app.models import (
    ReminderChannel,
    WhatsAppInbound,
    WhatsAppIntent,
    WhatsAppOutboundReply,
    WhatsAppReplyKind,
    WhatsAppReplyStatus,
)
from app.modules.notifications.replies import ReplyStats, run_replies
from app.modules.reminders.dispatch import run_tick
from app.modules.reminders.links import sign_manage_token
from app.modules.reminders.senders.base import SendError
from app.modules.reminders.senders.fake import FakeSender
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.reminder_helpers import AHORA, SECRETO_LINKS, Scene, commit_scene, dispatch_settings

pytestmark = pytest.mark.integration

COMPARTIDO = "100000000000009"


def _settings(settings: Settings, **cambios: Any) -> Settings:
    return dispatch_settings(  # type: ignore[no-any-return]
        settings, META_PHONE_NUMBER_ID=COMPARTIDO, **cambios
    )


async def _respuesta(
    maker: async_sessionmaker[AsyncSession],
    escena: Scene,
    kind: WhatsAppReplyKind,
    *,
    recibido: datetime = AHORA - timedelta(minutes=1),
) -> WhatsAppOutboundReply:
    async with maker() as session:
        entrante = WhatsAppInbound(
            clinic_id=escena.clinic.id,
            provider_message_id="wamid.FICTICIO-" + secrets.token_hex(6),
            phone_number_id=COMPARTIDO,
            patient_id=escena.patient.id,
            appointment_id=escena.appointment.id,
            intent=WhatsAppIntent.CONFIRM,
            routed_by="phone",
            occurred_at=recibido,
        )
        session.add(entrante)
        await session.flush()
        respuesta = WhatsAppOutboundReply(
            clinic_id=escena.clinic.id,
            inbound_id=entrante.id,
            patient_id=escena.patient.id,
            appointment_id=escena.appointment.id,
            kind=kind,
            available_at=recibido,
            expires_at=recibido + timedelta(hours=24),
        )
        session.add(respuesta)
        await session.commit()
    return respuesta


async def _releer(
    maker: async_sessionmaker[AsyncSession], respuesta: WhatsAppOutboundReply
) -> WhatsAppOutboundReply:
    async with maker() as session:
        fila: WhatsAppOutboundReply = (
            await session.execute(
                select(WhatsAppOutboundReply)
                .where(WhatsAppOutboundReply.id == respuesta.id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        return fila


async def _correr(
    maker: async_sessionmaker[AsyncSession],
    sender: FakeSender,
    settings: Settings,
    *,
    now: datetime = AHORA,
    **cambios: Any,
) -> ReplyStats:
    return await run_replies(maker, sender, _settings(settings, **cambios), now=lambda: now)


async def test_respuesta_pendiente_se_envia_como_texto_desde_su_numero(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True)
    respuesta = await _respuesta(rem_maker, escena, WhatsAppReplyKind.CONFIRMED)
    sender = FakeSender(ReminderChannel.WHATSAPP)

    stats = await _correr(rem_maker, sender, settings)

    assert stats.sent == 1
    [(sender_id, destino, cuerpo)] = sender.texts
    assert (sender_id, destino) == (COMPARTIDO, escena.patient.phone_e164)
    assert "confirmado" in cuerpo
    fila = await _releer(rem_maker, respuesta)
    assert fila.status is WhatsAppReplyStatus.SENT
    assert fila.sent_at == AHORA and fila.provider_message_id is not None
    assert sender.sent == []


async def test_numero_propio_de_la_clinica(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    propio = "2" + "".join(secrets.choice("0123456789") for _ in range(14))
    escena = await commit_scene(rem_maker, opt_in=True, whatsapp_phone_number_id=propio)
    await _respuesta(rem_maker, escena, WhatsAppReplyKind.CONFIRMED)
    sender = FakeSender(ReminderChannel.WHATSAPP)

    await _correr(rem_maker, sender, settings)

    assert sender.texts[0][0] == propio


async def test_ventana_vencida_no_envia(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True)
    respuesta = await _respuesta(
        rem_maker, escena, WhatsAppReplyKind.CONFIRMED, recibido=AHORA - timedelta(hours=25)
    )
    sender = FakeSender(ReminderChannel.WHATSAPP)

    await _correr(rem_maker, sender, settings)

    assert sender.texts == []
    fila = await _releer(rem_maker, respuesta)
    assert (fila.status, fila.reason) == (WhatsAppReplyStatus.EXPIRED, "window_closed")


async def test_paciente_dado_de_baja_solo_recibe_la_confirmacion_de_baja(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=False)
    confirmacion = await _respuesta(rem_maker, escena, WhatsAppReplyKind.CONFIRMED)
    baja = await _respuesta(rem_maker, escena, WhatsAppReplyKind.STOP_ACK)
    sender = FakeSender(ReminderChannel.WHATSAPP)

    await _correr(rem_maker, sender, settings)

    assert (await _releer(rem_maker, confirmacion)).status is WhatsAppReplyStatus.SKIPPED
    assert (await _releer(rem_maker, confirmacion)).reason == "no_consent"
    assert (await _releer(rem_maker, baja)).status is WhatsAppReplyStatus.SENT
    [(_, _, cuerpo)] = sender.texts
    assert "no te vamos a enviar" in cuerpo


async def test_fallo_reintentable_reprograma_y_luego_falla(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True)
    respuesta = await _respuesta(rem_maker, escena, WhatsAppReplyKind.CONFIRMED)
    sender = FakeSender(ReminderChannel.WHATSAPP)
    sender.failures = [SendError("http_5xx", retryable=True) for _ in range(3)]

    await _correr(rem_maker, sender, settings, WHATSAPP_REPLY_MAX_ATTEMPTS=2)
    fila = await _releer(rem_maker, respuesta)
    assert (fila.status, fila.attempts, fila.last_error) == (
        WhatsAppReplyStatus.PENDING,
        1,
        "http_5xx",
    )
    assert fila.available_at == AHORA + timedelta(minutes=5)

    await _correr(
        rem_maker, sender, settings, now=AHORA + timedelta(minutes=6), WHATSAPP_REPLY_MAX_ATTEMPTS=2
    )
    fila = await _releer(rem_maker, respuesta)
    assert (fila.status, fila.attempts) == (WhatsAppReplyStatus.FAILED, 2)


async def test_fallo_definitivo_falla_de_inmediato(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True)
    respuesta = await _respuesta(rem_maker, escena, WhatsAppReplyKind.CONFIRMED)
    sender = FakeSender(ReminderChannel.WHATSAPP)
    sender.failures = [SendError("meta_131047", retryable=False)]

    await _correr(rem_maker, sender, settings)

    fila = await _releer(rem_maker, respuesta)
    assert (fila.status, fila.last_error) == (WhatsAppReplyStatus.FAILED, "meta_131047")


async def test_dos_corridas_simultaneas_envian_una_vez(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escenas = [await commit_scene(rem_maker, opt_in=True) for _ in range(5)]
    for escena in escenas:
        await _respuesta(rem_maker, escena, WhatsAppReplyKind.CONFIRMED)
    sender = FakeSender(ReminderChannel.WHATSAPP)

    await asyncio.gather(_correr(rem_maker, sender, settings), _correr(rem_maker, sender, settings))

    assert len(sender.texts) == 5


async def test_lease_vencido_vuelve_a_pendiente(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True)
    respuesta = await _respuesta(rem_maker, escena, WhatsAppReplyKind.CONFIRMED)
    async with rem_maker() as session:
        fila = await session.get(WhatsAppOutboundReply, respuesta.id)
        assert fila is not None
        fila.status = WhatsAppReplyStatus.SENDING
        fila.claimed_at = AHORA - timedelta(minutes=30)
        fila.attempts = 1
        await session.commit()
    sender = FakeSender(ReminderChannel.WHATSAPP)

    stats = await _correr(rem_maker, sender, settings)

    assert stats.recovered == 1
    assert (await _releer(rem_maker, respuesta)).status is WhatsAppReplyStatus.SENT


@pytest.mark.parametrize("kind", list(WhatsAppReplyKind))
async def test_ningun_texto_lleva_el_nombre_del_paciente(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings, kind: WhatsAppReplyKind
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True)
    await _respuesta(rem_maker, escena, kind)
    sender = FakeSender(ReminderChannel.WHATSAPP)

    await _correr(rem_maker, sender, settings)

    [(_, _, cuerpo)] = sender.texts
    for parte in escena.patient.full_name.split():
        assert parte not in cuerpo


async def test_change_link_lleva_el_link_firmado_del_turno(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True)
    await _respuesta(rem_maker, escena, WhatsAppReplyKind.CHANGE_LINK)
    sender = FakeSender(ReminderChannel.WHATSAPP)

    await _correr(rem_maker, sender, settings)

    token = sign_manage_token(SECRETO_LINKS, escena.appointment.id)
    assert f"/g/{token}" in sender.texts[0][2]


async def test_change_contact_lleva_el_telefono_de_la_clinica(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True, contact_phone="+541155550000")
    await _respuesta(rem_maker, escena, WhatsAppReplyKind.CHANGE_CONTACT)
    sender = FakeSender(ReminderChannel.WHATSAPP)

    await _correr(rem_maker, sender, settings)

    assert "+541155550000" in sender.texts[0][2]


async def test_el_tick_del_worker_despacha_las_respuestas(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True)
    respuesta = await _respuesta(rem_maker, escena, WhatsAppReplyKind.CONFIRMED)
    sender = FakeSender(ReminderChannel.WHATSAPP)

    await run_tick(
        rem_maker, {ReminderChannel.WHATSAPP: sender}, _settings(settings), now=lambda: AHORA
    )

    assert (await _releer(rem_maker, respuesta)).status is WhatsAppReplyStatus.SENT
