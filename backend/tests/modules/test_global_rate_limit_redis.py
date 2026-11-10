"""Rate-limit global en Redis real (C-14, D5): el contador se comparte entre procesos.

Dos instancias de la app (como dos workers de uvicorn) contra el mismo Redis suman en la misma
ventana. Si Redis no responde, cada proceso degrada a memoria y sigue atendiendo.
"""

from __future__ import annotations

import httpx
import pytest
from app.core.settings import Settings
from app.main import create_app
from redis.asyncio import Redis

pytestmark = pytest.mark.integration


async def _get(app: object, path: str = "/openapi.json") -> httpx.Response:
    transport = httpx.ASGITransport(app=app, client=("10.9.9.9", 1))  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


async def test_dos_procesos_comparten_la_ventana(settings: Settings, redis_client: Redis) -> None:
    config = settings.model_copy(
        update={"BOOKING_RATE_LIMIT": "3/minute", "GLOBAL_RATE_LIMIT_BACKEND": "redis"}
    )
    proceso_a, proceso_b = create_app(config), create_app(config)
    try:
        codigos = [
            (await _get(proceso_a)).status_code,
            (await _get(proceso_b)).status_code,
            (await _get(proceso_a)).status_code,
        ]
        bloqueado = await _get(proceso_b)
    finally:
        for app in (proceso_a, proceso_b):
            await app.state.redis.aclose()
            await app.state.engine.dispose()

    assert codigos == [200, 200, 200]
    assert bloqueado.status_code == 429
    assert 1 <= int(bloqueado.headers["retry-after"]) <= 60
    assert await redis_client.exists("rl:global:ip:10.9.9.9") == 1


async def test_redis_caido_degrada_a_memoria(settings: Settings) -> None:
    config = settings.model_copy(
        update={
            "BOOKING_RATE_LIMIT": "2/minute",
            "GLOBAL_RATE_LIMIT_BACKEND": "redis",
            # Puerto cerrado: cada comando falla de inmediato.
            "REDIS_URL": "redis://127.0.0.1:1/0",
        }
    )
    app = create_app(config)
    try:
        codigos = [(await _get(app)).status_code for _ in range(3)]
    finally:
        await app.state.redis.aclose()
        await app.state.engine.dispose()

    assert codigos == [200, 200, 429]
