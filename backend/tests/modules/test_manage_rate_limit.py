"""Rate-limit de la gestión por token (C-08, D10): por IP y por hash, falla cerrada."""

from __future__ import annotations

import hashlib
from collections.abc import Callable

import httpx
import pytest
from app.core.redis import get_redis
from app.core.settings import Settings, get_settings
from app.models import AppointmentStatus
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tests.appointment_helpers import at, reload
from tests.conftest import MutableClock
from tests.manage_helpers import make_managed, new_token

pytestmark = pytest.mark.integration


def _con_settings(app: FastAPI, settings: Settings, **cambios: object) -> None:
    app.dependency_overrides[get_settings] = lambda: settings.model_copy(update=cambios)


async def test_rafaga_de_escrituras_con_el_mismo_token(
    app_instance: FastAPI,
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    managed = await make_managed(db_session, at(10, days=7))
    _con_settings(app_instance, settings, MANAGE_WRITE_TOKEN_RATE_LIMIT="2/60s")

    estados = [
        (await app_client.patch(managed.url, json={"action": "confirm"})).status_code
        for _ in range(2)
    ]
    tercera = await app_client.patch(managed.url, json={"action": "cancel"})

    assert estados == [200, 200]
    assert tercera.status_code == 429
    assert tercera.json() == {"detail": "rate_limited"}
    assert 0 < int(tercera.headers["Retry-After"]) <= 60
    assert tercera.headers["Cache-Control"] == "no-store"
    assert (await reload(db_session, managed.appointment.id)).status is AppointmentStatus.CONFIRMED


async def test_un_422_gasta_cupo_de_escritura(
    app_instance: FastAPI,
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    managed = await make_managed(db_session, at(10, days=7))
    appointment_id = managed.appointment.id
    _con_settings(app_instance, settings, MANAGE_WRITE_IP_RATE_LIMIT="1/60s")

    invalida = await app_client.patch(managed.url, json={"action": "volar"})
    cancelar = await app_client.patch(managed.url, json={"action": "cancel"})

    assert invalida.status_code == 422
    assert cancelar.status_code == 429
    assert (await reload(db_session, appointment_id)).status is AppointmentStatus.PENDING


async def test_barrido_de_tokens_desde_una_ip(
    app_instance: FastAPI,
    client_factory: Callable[..., httpx.AsyncClient],
    db_session: AsyncSession,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    """La IP agota su cupo con tokens inventados: 429 antes que 404; otra IP no se ve afectada."""
    _con_settings(app_instance, settings, MANAGE_READ_IP_RATE_LIMIT="3/60s")

    async with client_factory("10.7.0.1") as barredor, client_factory("10.7.0.2") as vecino:
        estados = [(await barredor.get(f"/api/manage/{new_token()}")).status_code for _ in range(3)]
        cuarta = await barredor.get(f"/api/manage/{new_token()}")
        otra_ip = await vecino.get(f"/api/manage/{new_token()}")

    assert estados == [404, 404, 404]
    assert cuarta.status_code == 429
    assert otra_ip.status_code == 404


async def test_redis_caido_da_503_y_no_muta(
    app_instance: FastAPI,
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    agenda_clock: MutableClock,
) -> None:
    managed = await make_managed(db_session, at(10, days=7))
    appointment_id = managed.appointment.id
    caido: Redis = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.5)

    async def _override() -> Redis:
        return caido

    app_instance.dependency_overrides[get_redis] = _override
    try:
        confirmar = await app_client.patch(managed.url, json={"action": "confirm"})
        vista = await app_client.get(managed.url)
    finally:
        await caido.aclose()

    for response in (confirmar, vista):
        assert response.status_code == 503
        assert response.json() == {"detail": "manage_unavailable"}
    assert (await reload(db_session, appointment_id)).status is AppointmentStatus.PENDING


async def test_las_claves_de_redis_usan_el_hash_y_no_el_token(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    agenda_clock: MutableClock,
) -> None:
    managed = await make_managed(db_session, at(10, days=7))

    await app_client.get(managed.url)
    await app_client.patch(managed.url, json={"action": "confirm"})

    claves = [
        k.decode() if isinstance(k, bytes) else k
        async for k in redis_client.scan_iter("rl:manage:*")
    ]
    huella = hashlib.sha256(managed.token.encode()).hexdigest()
    assert f"rl:manage:read:token:{huella}" in claves
    assert f"rl:manage:write:token:{huella}" in claves
    assert not [k for k in claves if managed.token in k]
