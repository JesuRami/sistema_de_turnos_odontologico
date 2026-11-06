"""Webhook de WhatsApp: verificación, firma, tamaño y tolerancia del payload (C-10, D2/D5).

Spec `reminders/whatsapp-webhook`: Verificación de suscripción, Firma obligatoria, Tolerancia a
campos nuevos de Meta. Postgres y Redis reales (regla 9); datos ficticios (regla 13).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx
import pytest
from app.core.settings import Settings, get_settings
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.whatsapp_helpers import (
    VERIFY_TOKEN,
    WEBHOOK,
    encode,
    envelope,
    sign,
    signed_headers,
    text_message,
    whatsapp_settings,
)

pytestmark = pytest.mark.integration

AHORA = datetime(2030, 1, 7, 8, 0, tzinfo=UTC)
TELEFONO_WA = "5491155550188"


@pytest.fixture()
def settings() -> Settings:
    base = Settings()  # type: ignore[call-arg]
    return whatsapp_settings(base, BOOKING_RATE_LIMIT="5/minute", WHATSAPP_WEBHOOK_MAX_BYTES=2048)


@pytest.fixture(autouse=True)
def _misma_configuracion(app_instance: FastAPI, settings: Settings) -> None:
    """El router lee `get_settings`: se apunta al mismo objeto para poder mutarlo en el test."""
    app_instance.dependency_overrides[get_settings] = lambda: settings


async def _conteos(session: AsyncSession) -> tuple[int, int]:
    from app.models import DeliveryEvent, WhatsAppInbound

    entrantes = await session.scalar(select(func.count()).select_from(WhatsAppInbound))
    eventos = await session.scalar(select(func.count()).select_from(DeliveryEvent))
    return int(entrantes or 0), int(eventos or 0)


def _payload_entrante() -> bytes:
    return encode(
        envelope(messages=[text_message(TELEFONO_WA, "STOP", AHORA, message_id="wamid.AUTH-0001")])
    )


# ------------------------------------------------------------------ GET de verificación


async def test_handshake_valido_devuelve_el_challenge(app_client: httpx.AsyncClient) -> None:
    respuesta = await app_client.get(
        WEBHOOK,
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": VERIFY_TOKEN,
            "hub.challenge": "1158201444",
        },
    )

    assert respuesta.status_code == 200
    assert respuesta.text == "1158201444"
    assert respuesta.headers["content-type"].startswith("text/plain")


@pytest.mark.parametrize(
    "params",
    [
        {"hub.mode": "subscribe", "hub.verify_token": "otro", "hub.challenge": "1"},
        {"hub.mode": "unsubscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "1"},
        {"hub.mode": "subscribe", "hub.challenge": "1"},
        {},
    ],
)
async def test_handshake_invalido_es_403_sin_eco(
    app_client: httpx.AsyncClient, params: dict[str, str]
) -> None:
    respuesta = await app_client.get(WEBHOOK, params=params)

    assert respuesta.status_code == 403
    assert "1" != respuesta.text


async def test_sin_token_configurado_todo_get_es_403(
    app_client: httpx.AsyncClient, settings: Settings
) -> None:
    settings.META_VERIFY_TOKEN = SecretStr("")

    respuesta = await app_client.get(
        WEBHOOK, params={"hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "1"}
    )

    assert respuesta.status_code == 403


# ------------------------------------------------------------------ POST firmado


async def test_post_sin_firma_es_401_sin_cambios_y_queda_registrado(
    app_client: httpx.AsyncClient, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    antes = await _conteos(db_session)
    caplog.set_level(logging.INFO)

    respuesta = await app_client.post(
        WEBHOOK, content=_payload_entrante(), headers={"Content-Type": "application/json"}
    )

    assert respuesta.status_code == 401
    assert await _conteos(db_session) == antes
    assert "webhook_signature_invalid" in caplog.text
    assert TELEFONO_WA not in caplog.text and "STOP" not in caplog.text
    assert "127.0.0.1" not in caplog.text


@pytest.mark.parametrize(
    "firma",
    [
        sign(b"otro cuerpo"),
        "sha1=" + sign(b"x").removeprefix("sha256="),
        "sha256=no-es-hex",
        "",
    ],
)
async def test_firma_invalida_es_401(
    app_client: httpx.AsyncClient, db_session: AsyncSession, firma: str
) -> None:
    antes = await _conteos(db_session)

    respuesta = await app_client.post(
        WEBHOOK,
        content=_payload_entrante(),
        headers={"X-Hub-Signature-256": firma, "Content-Type": "application/json"},
    )

    assert respuesta.status_code == 401
    assert await _conteos(db_session) == antes


async def test_sin_secreto_configurado_todo_post_es_401(
    app_client: httpx.AsyncClient, settings: Settings
) -> None:
    cuerpo = _payload_entrante()
    settings.META_APP_SECRET = SecretStr("")

    respuesta = await app_client.post(WEBHOOK, content=cuerpo, headers=signed_headers(cuerpo, ""))

    assert respuesta.status_code == 401


async def test_cuerpo_demasiado_grande_es_413(app_client: httpx.AsyncClient) -> None:
    cuerpo = encode({**envelope(statuses=[]), "relleno": "x" * 4096})

    respuesta = await app_client.post(WEBHOOK, content=cuerpo, headers=signed_headers(cuerpo))

    assert respuesta.status_code == 413


async def test_payload_firmado_con_campos_extra_se_acepta(
    app_client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    payload = envelope(statuses=[])
    payload["campo_nuevo_de_meta"] = {"x": 1}
    payload["entry"][0]["changes"][0]["value"]["otro_campo"] = [1, 2]
    cuerpo = encode(payload)
    caplog.set_level(logging.INFO)

    respuesta = await app_client.post(WEBHOOK, content=cuerpo, headers=signed_headers(cuerpo))

    assert respuesta.status_code == 200
    assert "webhook_payload_invalid" not in caplog.text


@pytest.mark.parametrize(
    "payload",
    [
        {"object": "whatsapp_business_account"},
        {"entry": "no-es-lista"},
        envelope(field="account_update"),
        [1, 2, 3],
    ],
)
async def test_payload_firmado_sin_estructura_es_200_sin_cambios(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
    payload: object,
) -> None:
    antes = await _conteos(db_session)
    caplog.set_level(logging.INFO)
    cuerpo = encode(payload)  # type: ignore[arg-type]

    respuesta = await app_client.post(WEBHOOK, content=cuerpo, headers=signed_headers(cuerpo))

    assert respuesta.status_code == 200
    assert await _conteos(db_session) == antes
    assert "webhook_payload_invalid" in caplog.text


async def test_json_invalido_firmado_es_200_sin_cambios(
    app_client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    cuerpo = b"{no es json"
    caplog.set_level(logging.INFO)

    respuesta = await app_client.post(WEBHOOK, content=cuerpo, headers=signed_headers(cuerpo))

    assert respuesta.status_code == 200
    assert "webhook_payload_invalid" in caplog.text


async def test_rafaga_firmada_no_recibe_429_del_rate_limit_global(
    app_client: httpx.AsyncClient,
) -> None:
    cuerpo = encode(envelope(statuses=[]))

    codigos = [
        (await app_client.post(WEBHOOK, content=cuerpo, headers=signed_headers(cuerpo))).status_code
        for _ in range(12)
    ]

    assert set(codigos) == {200}


async def test_el_stub_de_notifications_ya_no_existe(app_client: httpx.AsyncClient) -> None:
    respuesta = await app_client.get("/notifications/ping")

    assert respuesta.status_code == 404
