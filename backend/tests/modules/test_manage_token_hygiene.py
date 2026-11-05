"""Higiene del token y de los datos (C-08, D2, regla 13): nunca en logs, eventos ni errores."""

from __future__ import annotations

import logging
from datetime import timedelta

import httpx
import pytest
from app.core.settings import Settings, get_settings
from app.models import AppointmentEvent, AppointmentStatus
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.appointment_helpers import at
from tests.conftest import AGENDA_NOW, MutableClock
from tests.factories import make_appointment, make_patient
from tests.manage_helpers import make_managed

pytestmark = pytest.mark.integration

NOTA = "Nota privada ficticia del paciente 123"


async def test_el_token_no_aparece_en_logs_eventos_errores_ni_redis(
    app_instance: FastAPI,
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    managed = await make_managed(db_session, at(10, days=7))
    tarde = await make_managed(db_session, AGENDA_NOW + timedelta(hours=3), booking=managed.booking)
    vencido = await make_managed(
        db_session,
        AGENDA_NOW - timedelta(days=5),
        booking=managed.booking,
        status=AppointmentStatus.CONFIRMED,
    )
    b = managed.booking
    await make_appointment(
        db_session,
        b.clinic,
        patient=await make_patient(db_session, b.clinic),
        professional=b.professional,
        chair=b.chair,
        starts_at=at(11, days=7),
    )
    rango = {"from": at(0, days=7).isoformat(), "to": at(0, days=8).isoformat()}

    respuestas = [
        await app_client.get(managed.url),
        await app_client.get(f"{managed.url}/availability", params=rango),
        await app_client.patch(managed.url, json={"action": "cancel", "note": "x" * 201}),
        await app_client.patch(
            managed.url, json={"action": "reschedule", "starts_at": at(11, days=7).isoformat()}
        ),
        await app_client.patch(tarde.url, json={"action": "cancel"}),
        await app_client.get(vencido.url),
        await app_client.patch(managed.url, json={"action": "confirm"}),
        await app_client.patch(
            managed.url, json={"action": "cancel", "reason": "otro", "note": NOTA}
        ),
    ]
    app_instance.dependency_overrides[get_settings] = lambda: settings.model_copy(
        update={"MANAGE_READ_TOKEN_RATE_LIMIT": "1/60s"}
    )
    respuestas.append(await app_client.get(managed.url))

    assert [r.status_code for r in respuestas] == [200, 200, 422, 409, 409, 410, 200, 200, 429]
    tokens = (managed.token, tarde.token, vencido.token)
    for response in respuestas:
        for token in tokens:
            assert token not in response.text
    assert NOTA not in respuestas[7].text
    # Solo logs de la app: `httpx`/`httpcore` son el cliente de test pidiendo la URL (el access
    # log del servidor se redacta en uvicorn/nginx, ver backend/README.md).
    logs_app = " | ".join(
        r.getMessage() for r in caplog.records if not r.name.startswith(("httpx", "httpcore"))
    )
    for token in (*tokens, NOTA):
        assert token not in logs_app
    payloads = (
        await db_session.execute(
            select(AppointmentEvent.payload).where(
                AppointmentEvent.clinic_id == managed.booking.clinic.id
            )
        )
    ).scalars()
    volcado = str(list(payloads))
    for token in (*tokens, NOTA):
        assert token not in volcado
    claves = [k async for k in redis_client.scan_iter("*")]
    for token in tokens:
        assert not [k for k in claves if token in str(k)]


async def test_un_422_con_nota_no_la_ecoa(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    managed = await make_managed(db_session, at(10, days=7))
    nota_larga = "Dato sensible ficticio " * 12

    response = await app_client.patch(
        managed.url, json={"action": "cancel", "reason": "otro", "note": nota_larga}
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_request", "fields": ["cancel.note"]}
    assert "Dato sensible" not in response.text
