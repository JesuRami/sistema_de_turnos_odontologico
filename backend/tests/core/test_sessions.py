"""Sesiones de auth en Redis real: claves, TTL, rotación CAS y revocación."""

import asyncio
import hashlib
import uuid

import pytest
from app.modules.auth.sessions import (
    create_session,
    refresh_secret,
    revoke,
    revoke_all,
    revoke_by_sid,
    rotate,
    session_alive,
)
from redis.asyncio import Redis

pytestmark = pytest.mark.integration

UID = uuid.UUID("33333333-3333-4333-8333-333333333333")
CID = uuid.UUID("44444444-4444-4444-8444-444444444444")
UID_B = uuid.UUID("55555555-5555-4555-8555-555555555555")
TTL = 7 * 24 * 3600


async def test_crear_sesion_genera_claves_ttl_y_set_por_usuario(
    redis_client: Redis,
) -> None:
    """WHEN se crea una sesión THEN existen sess/rt, TTL ≤ 7d y el sid queda en auth:user."""
    tokens = await create_session(redis_client, user_id=UID, clinic_id=CID, ttl_s=TTL)

    assert await redis_client.exists(f"auth:sess:{tokens.sid}") == 1
    assert await redis_client.exists(f"auth:rt:{tokens.sid}") == 1
    ttl_sess = await redis_client.ttl(f"auth:sess:{tokens.sid}")
    ttl_rt = await redis_client.ttl(f"auth:rt:{tokens.sid}")
    assert 0 < ttl_sess <= TTL + 5
    assert 0 < ttl_rt <= TTL + 5
    assert tokens.sid in await redis_client.smembers(f"auth:user:{UID}")  # type: ignore[misc]


async def test_redis_solo_guarda_el_hash_del_secreto(redis_client: Redis) -> None:
    """WHEN se inspecciona Redis THEN el refresh en claro no aparece en ningún valor."""
    tokens = await create_session(redis_client, user_id=UID, clinic_id=CID, ttl_s=TTL)
    secreto = refresh_secret(tokens.refresh_token)
    esperado = hashlib.sha256(secreto.encode()).hexdigest()

    claves = [str(k) for k in await redis_client.keys("auth:*")]
    valores: list[str] = []
    for clave in claves:
        tipo = await redis_client.type(clave)
        if tipo == "hash":
            valores.extend(
                str(v) for v in (await redis_client.hgetall(clave)).values()  # type: ignore[misc]
            )
        elif tipo == "set":
            valores.extend(str(v) for v in await redis_client.smembers(clave))  # type: ignore[misc]
        else:
            valores.append(str(await redis_client.get(clave)))

    assert secreto not in valores
    assert tokens.refresh_token not in valores
    assert esperado in valores


async def test_rotacion_valida_invalida_el_refresh_anterior(redis_client: Redis) -> None:
    """WHEN se rota el refresh vigente THEN hay uno nuevo y el anterior falla."""
    tokens = await create_session(redis_client, user_id=UID, clinic_id=CID, ttl_s=TTL)

    resultado = await rotate(redis_client, tokens.refresh_token)

    assert resultado.status == "rotated"
    assert resultado.refresh_token is not None
    assert resultado.refresh_token != tokens.refresh_token
    assert resultado.user_id == UID
    assert resultado.clinic_id == CID
    anterior = await rotate(redis_client, tokens.refresh_token)
    # Rotación estricta (decisión 2): el anterior coincide con `prev` → reuso.
    assert anterior.status == "reuse"


async def test_la_clave_de_sesion_no_se_renueva_al_rotar(redis_client: Redis) -> None:
    """WHEN se rota THEN el TTL de la familia (vigencia absoluta) no se extiende."""
    tokens = await create_session(redis_client, user_id=UID, clinic_id=CID, ttl_s=TTL)
    ttl_antes = await redis_client.ttl(f"auth:sess:{tokens.sid}")

    await rotate(redis_client, tokens.refresh_token)

    ttl_despues = await redis_client.ttl(f"auth:sess:{tokens.sid}")
    assert 0 < ttl_despues <= ttl_antes


async def test_reuso_del_refresh_rotado_revoca_la_familia(redis_client: Redis) -> None:
    """WHEN se presenta un refresh ya rotado THEN reuse y la familia queda revocada."""
    tokens = await create_session(redis_client, user_id=UID, clinic_id=CID, ttl_s=TTL)
    primero = await rotate(redis_client, tokens.refresh_token)
    assert primero.refresh_token is not None
    segundo = await rotate(redis_client, primero.refresh_token)
    assert segundo.refresh_token is not None

    reuso = await rotate(redis_client, primero.refresh_token)

    assert reuso.status == "reuse"
    assert reuso.generation is not None
    assert await session_alive(redis_client, tokens.sid) is False
    assert await redis_client.exists(f"auth:rt:{tokens.sid}") == 0
    vigente = await rotate(redis_client, segundo.refresh_token)
    assert vigente.status == "missing"


async def test_secreto_basura_con_sid_valido_no_revoca(redis_client: Redis) -> None:
    """WHEN el secreto es basura pero el sid existe THEN invalid sin matar la sesión."""
    tokens = await create_session(redis_client, user_id=UID, clinic_id=CID, ttl_s=TTL)

    resultado = await rotate(redis_client, f"{tokens.sid}.{'x' * 43}")

    assert resultado.status == "invalid"
    assert await session_alive(redis_client, tokens.sid) is True


async def test_dos_rotaciones_concurrentes_solo_emiten_un_refresh(
    redis_client: Redis,
) -> None:
    """WHEN dos rotaciones compiten THEN una sola gana; la otra se trata como reuso."""
    tokens = await create_session(redis_client, user_id=UID, clinic_id=CID, ttl_s=TTL)

    resultados = await asyncio.gather(
        rotate(redis_client, tokens.refresh_token),
        rotate(redis_client, tokens.refresh_token),
    )

    estados = sorted(r.status for r in resultados)
    assert estados == ["reuse", "rotated"]
    # Rotación estricta sin ventana de gracia: el perdedor revoca la familia
    # (por eso la SPA de C-06 debe hacer refresh single-flight).
    assert await session_alive(redis_client, tokens.sid) is False


async def test_revoke_es_idempotente_y_solo_toca_su_sesion(redis_client: Redis) -> None:
    """WHEN se revoca dos veces THEN no falla y no afecta a otra sesión del usuario."""
    a = await create_session(redis_client, user_id=UID, clinic_id=CID, ttl_s=TTL)
    b = await create_session(redis_client, user_id=UID, clinic_id=CID, ttl_s=TTL)

    await revoke(redis_client, a.sid, UID)
    await revoke(redis_client, a.sid, UID)

    assert await session_alive(redis_client, a.sid) is False
    assert await session_alive(redis_client, b.sid) is True


async def test_revoke_by_sid_lee_el_usuario_del_hash(redis_client: Redis) -> None:
    """WHEN el logout solo tiene la cookie THEN revoca la familia y limpia el set."""
    tokens = await create_session(redis_client, user_id=UID, clinic_id=CID, ttl_s=TTL)

    await revoke_by_sid(redis_client, tokens.sid)

    assert await session_alive(redis_client, tokens.sid) is False
    assert tokens.sid not in await redis_client.smembers(f"auth:user:{UID}")  # type: ignore[misc]


async def test_revoke_all_solo_afecta_al_usuario(redis_client: Redis) -> None:
    """WHEN se revocan todas las sesiones de A THEN las de B siguen vivas."""
    a1 = await create_session(redis_client, user_id=UID, clinic_id=CID, ttl_s=TTL)
    a2 = await create_session(redis_client, user_id=UID, clinic_id=CID, ttl_s=TTL)
    otra = await create_session(redis_client, user_id=UID_B, clinic_id=CID, ttl_s=TTL)

    revocadas = await revoke_all(redis_client, UID)

    assert revocadas == 2
    assert await session_alive(redis_client, a1.sid) is False
    assert await session_alive(redis_client, a2.sid) is False
    assert await session_alive(redis_client, otra.sid) is True


@pytest.mark.parametrize("refresh", ["", "sin-punto", "sid.sin.secreto.extra"])
async def test_refresh_malformado_es_invalid(redis_client: Redis, refresh: str) -> None:
    """WHEN el valor de cookie no tiene `<sid>.<secreto>` THEN invalid sin tocar Redis."""
    resultado = await rotate(redis_client, refresh)

    assert resultado.status == "invalid"
