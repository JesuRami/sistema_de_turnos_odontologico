"""Acciones de la respuesta del paciente por WhatsApp (C-10, D7; spec whatsapp-webhook y
channel-consent). Postgres real; POST firmados; datos ficticios (regla 13).
"""

from __future__ import annotations

import secrets
from datetime import timedelta

import httpx
import pytest
from app.common.clock import get_now
from app.core.settings import Settings, get_settings
from app.models import (
    AppointmentEvent,
    AppointmentEventType,
    AppointmentOrigin,
    AppointmentStatus,
    CancellationReason,
    Consent,
    ConsentSource,
    ConsentStatus,
    ReminderStatus,
    WhatsAppInbound,
    WhatsAppOutboundReply,
    WhatsAppReplyKind,
)
from fastapi import FastAPI
from sqlalchemy import func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_clinic
from tests.reminder_helpers import AHORA, Scene, make_job, make_scene, statuses_of
from tests.whatsapp_helpers import (
    WEBHOOK,
    button_message,
    encode,
    envelope,
    signed_headers,
    text_message,
    whatsapp_settings,
)

pytestmark = pytest.mark.integration


@pytest.fixture()
def settings() -> Settings:
    return whatsapp_settings(Settings())  # type: ignore[call-arg]


@pytest.fixture(autouse=True)
def _config(app_instance: FastAPI, settings: Settings) -> None:
    app_instance.dependency_overrides[get_settings] = lambda: settings
    app_instance.dependency_overrides[get_now] = lambda: AHORA


def _wamid() -> str:
    return "wamid.FICTICIO-" + secrets.token_hex(8)


def _wa(escena: Scene) -> str:
    assert escena.patient.phone_e164 is not None
    return escena.patient.phone_e164.removeprefix("+")


async def _post(client: httpx.AsyncClient, mensaje: dict[str, object]) -> httpx.Response:
    cuerpo = encode(envelope(messages=[mensaje]))
    respuesta = await client.post(WEBHOOK, content=cuerpo, headers=signed_headers(cuerpo))
    assert respuesta.status_code == 200, respuesta.text
    return respuesta


async def _texto(client: httpx.AsyncClient, escena: Scene, texto: str, **kw: object) -> str:
    message_id = str(kw.pop("message_id", None) or _wamid())
    await _post(client, text_message(_wa(escena), texto, AHORA, message_id=message_id, **kw))  # type: ignore[arg-type]
    return message_id


async def _respuestas(session: AsyncSession) -> list[WhatsAppOutboundReply]:
    return list(
        (
            await session.execute(
                select(WhatsAppOutboundReply).order_by(WhatsAppOutboundReply.created_at)
            )
        )
        .scalars()
        .all()
    )


async def _kinds(session: AsyncSession) -> list[WhatsAppReplyKind]:
    return [r.kind for r in await _respuestas(session)]


async def _eventos(session: AsyncSession, escena: Scene) -> list[AppointmentEvent]:
    return list(
        (
            await session.execute(
                select(AppointmentEvent)
                .where(AppointmentEvent.appointment_id == escena.appointment.id)
                .order_by(AppointmentEvent.created_at, AppointmentEvent.id)
            )
        )
        .scalars()
        .all()
    )


async def _estado(session: AsyncSession, escena: Scene) -> AppointmentStatus:
    await session.refresh(escena.appointment)
    return escena.appointment.status


async def _online_pendiente(session: AsyncSession, **kw: object) -> Scene:
    escena = await make_scene(
        session,
        opt_in=True,
        status=AppointmentStatus.PENDING,
        origin=AppointmentOrigin.ONLINE,
        **kw,  # type: ignore[arg-type]
    )
    for paso in ("t_72h", "t_24h", "t_3h"):
        horas = int(paso[2:-1])
        await make_job(
            session,
            escena.appointment,
            step=paso,
            scheduled_for=escena.appointment.starts_at - timedelta(hours=horas),
        )
    return escena


# ------------------------------------------------------------------ SÍ


async def test_si_confirma_un_turno_online_pendiente(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    escena = await _online_pendiente(db_session)

    await _texto(app_client, escena, "SÍ")

    assert await _estado(db_session, escena) is AppointmentStatus.CONFIRMED
    ultimo = (await _eventos(db_session, escena))[-1]
    assert ultimo.event is AppointmentEventType.CONFIRMED
    assert ultimo.payload["source"] == "whatsapp"
    estados = await statuses_of(db_session, escena.appointment.id)
    assert estados["t_72h/whatsapp"] == ReminderStatus.CANCELLED.value
    assert estados["t_24h/whatsapp"] == ReminderStatus.CANCELLED.value
    assert estados["t_3h/whatsapp"] == ReminderStatus.SCHEDULED.value
    assert await _kinds(db_session) == [WhatsAppReplyKind.CONFIRMED]


async def test_boton_confirmar_citando_el_recordatorio(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    escena = await _online_pendiente(db_session)
    pid = _wamid()
    await make_job(
        db_session,
        escena.appointment,
        step="created",
        status=ReminderStatus.SENT,
        sent_at=AHORA,
        provider_message_id=pid,
    )

    await _post(
        app_client,
        button_message(_wa(escena), "confirm", AHORA, message_id=_wamid(), context_id=pid),
    )

    assert await _estado(db_session, escena) is AppointmentStatus.CONFIRMED


async def test_si_a_un_turno_confirmado_es_replay(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    escena = await make_scene(db_session, opt_in=True)

    await _texto(app_client, escena, "si")

    ultimo = (await _eventos(db_session, escena))[-1]
    assert ultimo.event is AppointmentEventType.UPDATED
    assert ultimo.payload == {"idempotent_replay": True, "action": "confirm", "source": "whatsapp"}
    assert await _kinds(db_session) == [WhatsAppReplyKind.CONFIRMED]


async def test_si_a_un_turno_cancelado_no_cambia_y_deriva(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    escena = await _online_pendiente(db_session)
    pid = _wamid()
    await make_job(
        db_session,
        escena.appointment,
        step="created",
        status=ReminderStatus.SENT,
        sent_at=AHORA,
        provider_message_id=pid,
    )
    turno = escena.appointment
    turno.status = AppointmentStatus.CANCELLED
    turno.cancellation_reason = CancellationReason.PACIENTE
    turno.cancelled_at = AHORA
    await db_session.flush()
    antes = len(await _eventos(db_session, escena))

    await _texto(app_client, escena, "si", context_id=pid)

    assert await _estado(db_session, escena) is AppointmentStatus.CANCELLED
    assert len(await _eventos(db_session, escena)) == antes
    assert await _kinds(db_session) == [WhatsAppReplyKind.INACTIVE]


# ------------------------------------------------------------------ NO / cambiar


async def test_no_dentro_de_la_ventana_manda_el_link_sin_cambiar(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    escena = await _online_pendiente(db_session, starts_in=timedelta(hours=48))
    antes = len(await _eventos(db_session, escena))

    await _texto(app_client, escena, "NO")

    assert await _estado(db_session, escena) is AppointmentStatus.PENDING
    assert len(await _eventos(db_session, escena)) == antes
    assert await _kinds(db_session) == [WhatsAppReplyKind.CHANGE_LINK]


async def test_no_fuera_de_la_ventana_manda_el_contacto(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    escena = await _online_pendiente(db_session, starts_in=timedelta(hours=3))

    await _texto(app_client, escena, "no")

    assert await _estado(db_session, escena) is AppointmentStatus.PENDING
    assert await _kinds(db_session) == [WhatsAppReplyKind.CHANGE_CONTACT]


# ------------------------------------------------------------------ ambiguo


async def test_ambiguo_deriva_desde_la_clinica_de_menor_id(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    escena = await _online_pendiente(db_session)
    otra = await make_scene(
        db_session,
        clinic=await make_clinic(db_session),
        status=AppointmentStatus.PENDING,
        origin=AppointmentOrigin.ONLINE,
    )
    otra.patient.phone_e164 = escena.patient.phone_e164
    await db_session.flush()

    await _texto(app_client, escena, "si")

    assert await _estado(db_session, escena) is AppointmentStatus.PENDING
    assert await _estado(db_session, otra) is AppointmentStatus.PENDING
    entrantes = (await db_session.execute(select(WhatsAppInbound))).scalars().all()
    assert {e.clinic_id for e in entrantes} == {escena.clinic.id, otra.clinic.id}
    [respuesta] = await _respuestas(db_session)
    assert respuesta.kind is WhatsAppReplyKind.AMBIGUOUS
    assert respuesta.clinic_id == min(escena.clinic.id, otra.clinic.id)


# ------------------------------------------------------------------ STOP


async def _consentimientos(session: AsyncSession, escena: Scene) -> list[Consent]:
    return list(
        (await session.execute(select(Consent).where(Consent.patient_id == escena.patient.id)))
        .scalars()
        .all()
    )


async def test_baja_con_contexto(app_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    escena = await _online_pendiente(db_session)
    pid = _wamid()
    await make_job(
        db_session,
        escena.appointment,
        step="created",
        status=ReminderStatus.SENT,
        sent_at=AHORA,
        provider_message_id=pid,
    )

    await _texto(app_client, escena, "BAJA", context_id=pid)

    await db_session.refresh(escena.patient)
    assert escena.patient.whatsapp_opt_in is False
    [consentimiento] = await _consentimientos(db_session, escena)
    assert (consentimiento.status, consentimiento.source, consentimiento.changed_by_user_id) == (
        ConsentStatus.OPT_OUT,
        ConsentSource.WHATSAPP_REPLY,
        None,
    )
    estados = await statuses_of(db_session, escena.appointment.id)
    assert estados["t_72h/whatsapp"] == ReminderStatus.SKIPPED.value
    assert estados["t_3h/whatsapp"] == ReminderStatus.SKIPPED.value
    assert await _kinds(db_session) == [WhatsAppReplyKind.STOP_ACK]


async def test_baja_ambigua_da_de_baja_ambas_fichas_con_una_confirmacion(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    escena = await _online_pendiente(db_session)
    otra = await make_scene(db_session, clinic=await make_clinic(db_session), opt_in=True)
    otra.patient.phone_e164 = escena.patient.phone_e164
    await db_session.flush()

    await _texto(app_client, escena, "STOP")

    for ficha in (escena.patient, otra.patient):
        await db_session.refresh(ficha)
        assert ficha.whatsapp_opt_in is False
    assert await _kinds(db_session) == [WhatsAppReplyKind.STOP_ACK]


async def test_baja_repetida_no_agrega_nada(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    escena = await _online_pendiente(db_session)

    await _texto(app_client, escena, "STOP")
    await _texto(app_client, escena, "stop")

    assert len(await _consentimientos(db_session, escena)) == 1
    assert await _kinds(db_session) == [WhatsAppReplyKind.STOP_ACK]


# ------------------------------------------------------------------ deduplicación y PII


async def test_reenvio_del_mismo_mensaje_no_repite_efectos(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    escena = await _online_pendiente(db_session)
    mensaje = text_message(_wa(escena), "si", AHORA, message_id=_wamid())

    await _post(app_client, mensaje)
    eventos = len(await _eventos(db_session, escena))
    await _post(app_client, mensaje)

    assert len(await _eventos(db_session, escena)) == eventos
    assert await _kinds(db_session) == [WhatsAppReplyKind.CONFIRMED]
    total = await db_session.scalar(select(func.count()).select_from(WhatsAppInbound))
    assert total == 1


async def test_el_entrante_no_guarda_texto_ni_telefono(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    escena = await _online_pendiente(db_session)
    texto = "mi dni es 30111222 y mi telefono otro"

    await _texto(app_client, escena, texto)

    [fila] = (await db_session.execute(select(WhatsAppInbound))).scalars().all()
    valores = " ".join(str(getattr(fila, c.key)) for c in inspect(WhatsAppInbound).columns)
    assert "30111222" not in valores
    assert _wa(escena) not in valores
    assert await _kinds(db_session) == []
