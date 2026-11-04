"""`consume` (C-07, D2): cupo de ventana fija en Redis con 429 y 503 fail-closed parametrizado."""

import uuid

import pytest
from app.common.exceptions import DomainError
from app.common.rate_limit_guard import consume
from redis.asyncio import Redis

pytestmark = pytest.mark.integration


def _key() -> str:
    return f"rl:test:{uuid.uuid4().hex}"


async def test_dentro_del_cupo_pasa(redis_client: Redis) -> None:
    key = _key()

    for _ in range(3):
        await consume(redis_client, key, "3/60s", unavailable_code="booking_unavailable")


async def test_excedido_da_429_rate_limited_con_retry_after(redis_client: Redis) -> None:
    key = _key()
    for _ in range(2):
        await consume(redis_client, key, "2/60s", unavailable_code="booking_unavailable")

    with pytest.raises(DomainError) as exc_info:
        await consume(redis_client, key, "2/60s", unavailable_code="booking_unavailable")

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == "rate_limited"
    retry_after = int((exc_info.value.headers or {})["Retry-After"])
    assert 0 < retry_after <= 60


async def test_las_claves_distintas_no_comparten_cupo(redis_client: Redis) -> None:
    una, otra = _key(), _key()
    await consume(redis_client, una, "1/60s", unavailable_code="booking_unavailable")

    await consume(redis_client, otra, "1/60s", unavailable_code="booking_unavailable")


@pytest.mark.parametrize("codigo", ["booking_unavailable", "auth_unavailable"])
async def test_redis_caido_da_503_con_el_codigo_pedido(codigo: str) -> None:
    # Puerto cerrado: la conexión falla de verdad (sin mocks).
    caido = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.5)
    try:
        with pytest.raises(DomainError) as exc_info:
            await consume(caido, _key(), "5/60s", unavailable_code=codigo)
    finally:
        await caido.aclose()

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == codigo
