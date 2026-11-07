"""Timeline de recordatorios por turno (C-11, D3; spec reminders/delivery-timeline).

Postgres y Redis reales; jobs y eventos sembrados como los escribirían el motor y el webhook.
Datos ficticios (regla 13).
"""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
from app.core.settings import Settings
from app.models import DeliveryEventType, ReminderStatus
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import MutableClock
from tests.timeline_helpers import (
    NOW,
    E,
    escena,
    evento,
    job,
    otro_profesional,
    reenvio,
    timeline_url,
)

pytestmark = pytest.mark.integration


async def test_recepcion_ve_pasos_y_eventos_de_su_clinica(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await escena(db_session, redis_client, settings)
    for paso in ("t_72h", "t_24h"):
        fila = await job(db_session, e.appointment, paso)
        await evento(db_session, fila, DeliveryEventType.SENT, fila.scheduled_for, attempt=1)
    await job(db_session, e.appointment, "t_3h", status=ReminderStatus.SCHEDULED)

    respuesta = await app_client.get(timeline_url(e.appointment.id), headers=e.headers["recepcion"])

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["appointment_id"] == str(e.appointment.id)
    assert cuerpo["timezone"] == e.staff.clinic.timezone
    assert [(s["step"], s["channel"]) for s in cuerpo["steps"]] == [
        ("t_72h", "whatsapp"),
        ("t_24h", "whatsapp"),
        ("t_3h", "whatsapp"),
    ]
    assert cuerpo["steps"][0]["status"] == "sent"
    assert [ev["type"] for ev in cuerpo["steps"][0]["events"]] == ["sent"]
    # Un paso pendiente muestra el hito sintético `scheduled` como primer evento.
    assert cuerpo["steps"][2]["events"][0]["type"] == "scheduled"


async def test_orden_alta_72_24_3_y_whatsapp_antes_que_email(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await escena(db_session, redis_client, settings)
    for paso, canal in (
        ("t_3h", E),
        ("t_24h", E),
        ("t_3h", None),
        ("created", None),
        ("t_72h", None),
    ):
        if canal is None:
            await job(db_session, e.appointment, paso)
        else:
            await job(db_session, e.appointment, paso, canal)

    cuerpo = (
        await app_client.get(timeline_url(e.appointment.id), headers=e.headers["admin"])
    ).json()

    assert [(s["step"], s["channel"]) for s in cuerpo["steps"]] == [
        ("created", "whatsapp"),
        ("t_72h", "whatsapp"),
        ("t_24h", "email"),
        ("t_3h", "whatsapp"),
        ("t_3h", "email"),
    ]


async def test_turno_de_otra_clinica_es_404(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    a = await escena(db_session, redis_client, settings)
    b = await escena(db_session, redis_client, settings)
    await job(db_session, b.appointment)

    respuesta = await app_client.get(timeline_url(b.appointment.id), headers=a.headers["admin"])

    assert respuesta.status_code == 404
    assert respuesta.json() == {"detail": "not_found"}


async def test_odontologo_ajeno_404_y_propio_200(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    propio = await escena(db_session, redis_client, settings)
    otro = await otro_profesional(db_session, propio.staff)
    ajeno = await escena(
        db_session,
        redis_client,
        settings,
        staff=propio.staff,
        professional=otro,
        starts_in=timedelta(days=4),
    )
    await job(db_session, propio.appointment)
    await job(db_session, ajeno.appointment)
    odontologo = propio.headers["odontologo"]

    assert (
        await app_client.get(timeline_url(ajeno.appointment.id), headers=odontologo)
    ).status_code == 404
    respuesta = await app_client.get(timeline_url(propio.appointment.id), headers=odontologo)
    assert respuesta.status_code == 200
    assert respuesta.json()["steps"][0]["can_resend"] is False


async def test_sin_sesion_es_401(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await escena(db_session, redis_client, settings)

    assert (await app_client.get(timeline_url(e.appointment.id))).status_code == 401


async def test_la_respuesta_no_expone_pii_ni_ids_del_proveedor(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await escena(db_session, redis_client, settings)
    fila = await job(
        db_session, e.appointment, provider_message_id="wamid.TIMELINE-FICTICIO", cost_micros=12500
    )
    await evento(
        db_session,
        fila,
        DeliveryEventType.SENT,
        fila.scheduled_for,
        attempt=1,
        kind="template",
        cost_micros=12500,
        provider_message_id="wamid.TIMELINE-FICTICIO",
        link="https://example.com/m/token-ficticio",
    )
    await reenvio(db_session, fila, e.recepcion, NOW - timedelta(hours=1), note="Pidió reenvío")

    texto = (
        await app_client.get(timeline_url(e.appointment.id), headers=e.headers["recepcion"])
    ).text

    for prohibido in (
        "wamid.TIMELINE-FICTICIO",
        "token-ficticio",
        "Pidió reenvío",
        e.patient.full_name,
        str(e.patient.phone_e164),
        str(e.patient.email),
    ):
        assert prohibido not in texto
    assert "12500" in texto


async def test_dos_lecturas_seguidas_devuelven_lo_mismo(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await escena(db_session, redis_client, settings)
    fila = await job(db_session, e.appointment)
    await evento(db_session, fila, DeliveryEventType.SENT, fila.scheduled_for)
    await evento(
        db_session, fila, DeliveryEventType.DELIVERED, fila.scheduled_for + timedelta(minutes=1)
    )

    url = timeline_url(e.appointment.id)
    primera = (await app_client.get(url, headers=e.headers["recepcion"])).json()
    segunda = (await app_client.get(url, headers=e.headers["recepcion"])).json()

    assert primera == segunda
    assert primera["steps"][0]["status"] == "delivered"
