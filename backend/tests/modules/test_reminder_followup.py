"""Lista de seguimiento: sin confirmar y fallos de envío (C-11, D8; spec followup-board).

Postgres y Redis reales; jobs y eventos sembrados directo. Datos ficticios (regla 13).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from app.core.settings import Settings
from app.models import (
    AppointmentOrigin,
    AppointmentStatus,
    CancellationReason,
    Clinic,
    DeliveryEventType,
    ReminderStatus,
)
from redis.asyncio import Redis
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import MutableClock
from tests.timeline_helpers import NOW, Escena, escena, evento, job

pytestmark = pytest.mark.integration

URL = "/api/reminders/follow-up"
BA = ZoneInfo("America/Argentina/Buenos_Aires")
DESDE = NOW
HASTA = NOW + timedelta(days=10)


def _rango(desde: datetime = DESDE, hasta: datetime = HASTA) -> dict[str, str]:
    return {"from": desde.isoformat(), "to": hasta.isoformat()}


async def _get(
    client: httpx.AsyncClient, e: Escena, rol: str = "recepcion", **params: Any
) -> httpx.Response:
    return await client.get(URL, params=params or _rango(), headers=e.headers[rol])


async def _pendiente(db: AsyncSession, redis: Redis, settings: Settings, **kw: Any) -> Escena:
    return await escena(
        db, redis, settings, status=AppointmentStatus.PENDING, origin=AppointmentOrigin.ONLINE, **kw
    )


async def _enviado(db: AsyncSession, e: Escena, step: str = "t_24h", **kw: Any) -> None:
    fila = await job(db, e.appointment, step, **kw)
    await evento(db, fila, DeliveryEventType.SENT, fila.scheduled_for, attempt=1)


def _filas(respuesta: httpx.Response) -> dict[str, list[str]]:
    assert respuesta.status_code == 200, respuesta.text
    return {f["appointment_id"]: f["reasons"] for f in respuesta.json()["items"]}


async def test_pendiente_con_24h_enviado_no_respondio(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _pendiente(db_session, redis_client, settings)
    await _enviado(db_session, e)

    respuesta = await _get(app_client, e)

    assert _filas(respuesta) == {str(e.appointment.id): ["no_response"]}
    [fila] = respuesta.json()["items"]
    assert fila["patient_name"] == e.patient.full_name
    assert fila["can_confirm"] is True
    assert fila["last_reminder"]["step"] == "t_24h"
    assert respuesta.json()["totals"] == {"no_response": 1, "delivery_failed": 0}


async def test_confirmado_no_aparece(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await escena(db_session, redis_client, settings, origin=AppointmentOrigin.ONLINE)
    await _enviado(db_session, e)

    assert _filas(await _get(app_client, e)) == {}


async def test_clinica_sin_24h_usa_el_ultimo_paso_de_confirmacion(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _pendiente(db_session, redis_client, settings)
    await db_session.execute(
        update(Clinic)
        .where(Clinic.id == e.staff.clinic.id)
        .values(
            reminder_steps=[
                {"offset_h": 72, "channel": "whatsapp"},
                {"offset_h": 3, "channel": "whatsapp"},
            ]
        )
    )
    await _enviado(db_session, e, "t_72h")

    assert _filas(await _get(app_client, e)) == {str(e.appointment.id): ["no_response"]}


async def test_con_24h_configurado_el_72h_enviado_no_alcanza(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _pendiente(db_session, redis_client, settings)
    await _enviado(db_session, e, "t_72h")
    await job(db_session, e.appointment, "t_24h", status=ReminderStatus.SCHEDULED)

    assert _filas(await _get(app_client, e)) == {}


async def test_24h_fallido_es_fallo_de_envio_y_no_no_respondio(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _pendiente(db_session, redis_client, settings)
    await _enviado(db_session, e, status=ReminderStatus.FAILED, last_error="meta_131026")

    respuesta = await _get(app_client, e)

    assert _filas(respuesta) == {str(e.appointment.id): ["delivery_failed"]}
    assert respuesta.json()["items"][0]["last_reminder"]["last_error"] == "meta_131026"


async def test_fallo_del_3h_de_un_confirmado_y_reenvio_exitoso(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    fallido = await escena(db_session, redis_client, settings)
    await job(db_session, fallido.appointment, "t_3h", status=ReminderStatus.FAILED)
    reenviado = await escena(
        db_session, redis_client, settings, staff=fallido.staff, starts_in=timedelta(days=4)
    )
    await _enviado(db_session, reenviado, "t_3h")

    filas = _filas(await _get(app_client, fallido))

    assert filas == {str(fallido.appointment.id): ["delivery_failed"]}


async def test_cancelado_y_pasado_no_aparecen(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    cancelado = await _pendiente(db_session, redis_client, settings)
    await job(db_session, cancelado.appointment, "t_3h", status=ReminderStatus.FAILED)
    cancelado.appointment.status = AppointmentStatus.CANCELLED
    cancelado.appointment.cancelled_at = NOW
    cancelado.appointment.cancellation_reason = CancellationReason.PACIENTE
    pasado = await _pendiente(
        db_session,
        redis_client,
        settings,
        staff=cancelado.staff,
        starts_in=-timedelta(hours=1),
    )
    await _enviado(db_session, pasado)
    await db_session.flush()

    respuesta = await _get(
        app_client, cancelado, **_rango(desde=NOW - timedelta(days=1), hasta=HASTA)
    )

    assert _filas(respuesta) == {}


async def test_odontologo_recibe_403(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _pendiente(db_session, redis_client, settings)

    respuesta = await _get(app_client, e, "odontologo")

    assert respuesta.status_code == 403
    assert respuesta.json()["detail"] == "forbidden_role"


async def test_aislamiento_entre_clinicas(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    a = await _pendiente(db_session, redis_client, settings)
    b = await _pendiente(db_session, redis_client, settings)
    await _enviado(db_session, a)
    await _enviado(db_session, b)
    await job(db_session, b.appointment, "t_3h", status=ReminderStatus.FAILED)

    respuesta = await _get(app_client, a)

    assert _filas(respuesta) == {str(a.appointment.id): ["no_response"]}
    assert respuesta.json()["totals"] == {"no_response": 1, "delivery_failed": 0}


async def test_rangos_invalidos(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _pendiente(db_session, redis_client, settings)

    largo = await _get(app_client, e, **_rango(hasta=DESDE + timedelta(days=32)))
    invertido = await _get(app_client, e, **_rango(desde=HASTA, hasta=DESDE))

    assert (largo.status_code, largo.json()["detail"]) == (422, "range_too_large")
    assert (invertido.status_code, invertido.json()["detail"]) == (422, "invalid_range")


async def test_turno_de_las_2330_locales_cae_en_su_dia(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    dia = (NOW + timedelta(days=3)).astimezone(BA).date()
    noche = datetime.combine(dia, time(23, 30), tzinfo=BA)
    e = await _pendiente(db_session, redis_client, settings, starts_in=noche - NOW)
    await _enviado(db_session, e)
    inicio = datetime.combine(dia, time(0), tzinfo=BA)
    fin = inicio + timedelta(days=1)

    ese_dia = _filas(await _get(app_client, e, **_rango(desde=inicio, hasta=fin)))
    siguiente = _filas(
        await _get(app_client, e, **_rango(desde=fin, hasta=fin + timedelta(days=1)))
    )

    assert str(e.appointment.id) in ese_dia
    assert siguiente == {}


async def test_la_respuesta_no_incluye_contacto_ni_ids_del_proveedor(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _pendiente(db_session, redis_client, settings)
    await _enviado(db_session, e, provider_message_id="wamid.SEGUIMIENTO-FICTICIO")

    texto = (await _get(app_client, e)).text

    for prohibido in (
        str(e.patient.phone_e164),
        str(e.patient.email),
        "wamid.SEGUIMIENTO-FICTICIO",
    ):
        assert prohibido not in texto


async def test_paginacion_por_cursor(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    primero = await _pendiente(db_session, redis_client, settings)
    segundo = await _pendiente(
        db_session, redis_client, settings, staff=primero.staff, starts_in=timedelta(days=4)
    )
    for e in (primero, segundo):
        await _enviado(db_session, e)

    uno = await _get(app_client, primero, **_rango(), limit="1")
    dos = await _get(app_client, primero, **_rango(), limit="1", cursor=uno.json()["next_cursor"])

    assert list(_filas(uno)) == [str(primero.appointment.id)]
    assert list(_filas(dos)) == [str(segundo.appointment.id)]
    assert dos.json()["next_cursor"] is None
    assert uno.json()["totals"]["no_response"] == 2
