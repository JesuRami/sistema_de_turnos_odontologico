"""Cliente Redis compartido por app (C-03): PING real y reutilización entre dependencias."""

from urllib.parse import urlparse

import pytest
from app.core.redis import auth_redis_url, create_redis_client, get_redis
from app.core.settings import Settings
from app.main import create_app
from fastapi import FastAPI
from redis.asyncio import Redis
from starlette.requests import Request

pytestmark = pytest.mark.integration


def _settings(settings: Settings) -> Settings:
    return settings.model_copy(update={"REDIS_AUTH_DB": 15})


def _request_for(app: FastAPI) -> Request:
    return Request({"type": "http", "app": app, "headers": [], "method": "GET", "path": "/"})


async def test_cliente_responde_ping_contra_redis_real(
    settings: Settings, redis_client: Redis
) -> None:
    """WHEN se crea el cliente de auth THEN responde PING contra REDIS_URL."""
    _ = redis_client  # gate de servicio real
    client = create_redis_client(_settings(settings))
    try:
        assert await client.ping() is True
    finally:
        await client.aclose()


async def test_la_app_reutiliza_el_mismo_cliente(settings: Settings, redis_client: Redis) -> None:
    _ = redis_client
    """WHEN dos dependencias piden Redis en la misma app THEN reciben el mismo cliente."""
    app = create_app(_settings(settings))
    primero = await get_redis(_request_for(app))
    segundo = await get_redis(_request_for(app))

    assert primero is segundo
    assert primero is app.state.redis
    assert await primero.ping() is True


def test_auth_redis_url_usa_la_base_logica_configurada(
    settings: Settings, redis_client: Redis
) -> None:
    _ = redis_client
    """WHEN REDIS_AUTH_DB=15 THEN la URL de auth apunta a la base 15 sin tocar el host."""
    url = auth_redis_url(_settings(settings))

    # El host/puerto se conservan del REDIS_URL configurado: en Compose es `redis:6379`,
    # en local `localhost:6379`. Hardcodear `localhost` ataba el test al host de dev.
    esperado = urlparse(str(settings.REDIS_URL))
    obtenido = urlparse(url)
    assert obtenido.path == "/15"
    assert (obtenido.hostname, obtenido.port) == (esperado.hostname, esperado.port)
