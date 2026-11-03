"""Login del personal: sesión, cookie, errores genéricos, rate-limit y rehash."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from app.core.security import hash_password, needs_rehash, verify_password
from app.core.settings import Settings
from app.models import AuthEvent, AuthEventType, Clinic, User
from app.modules.auth.cookies import refresh_cookie_name
from argon2 import PasswordHasher
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_clinic, make_user, unique_email

pytestmark = pytest.mark.integration

PASSWORD = "clave-ficticia-123"


async def _usuario(db_session: AsyncSession, **overrides: object) -> tuple[Clinic, User]:
    clinic = await make_clinic(db_session)
    valores: dict[str, object] = {
        "email": unique_email("staff.login"),
        "password_hash": hash_password(PASSWORD),
        "must_change_password": False,
    }
    valores.update(overrides)
    user = await make_user(db_session, clinic, **valores)
    return clinic, user


async def _post_login(
    client: httpx.AsyncClient,
    email: str,
    password: str = PASSWORD,
    **extra: object,
) -> httpx.Response:
    body = {"email": email, "password": password, **extra}
    return await client.post("/api/auth/login", json=body)


async def test_login_correcto_emite_access_cookie_y_perfil(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """WHEN credenciales válidas THEN 200 con access, cookie HttpOnly y perfil."""
    _clinic, user = await _usuario(db_session)

    response = await _post_login(app_client, user.email)

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert 0 < body["expires_in"] <= 900
    assert body["user"]["id"] == str(user.id)
    assert body["user"]["email"] == user.email
    assert body["user"]["must_change_password"] is False
    assert "refresh_token" not in response.text

    cookie = response.headers.get("set-cookie", "")
    nombre = refresh_cookie_name(settings)
    assert f"{nombre}=" in cookie
    assert "httponly" in cookie.lower()
    assert "samesite=lax" in cookie.lower()
    assert "secure" not in cookie.lower()


async def test_login_actualiza_last_login_at(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """WHEN el login es correcto THEN `last_login_at` queda marcado."""
    _clinic, user = await _usuario(db_session)

    response = await _post_login(app_client, user.email)

    assert response.status_code == 200
    fila = (await db_session.execute(select(User).where(User.id == user.id))).scalar_one()
    assert fila.last_login_at is not None


async def test_la_cookie_sobrevive_entre_requests_del_mismo_cliente(
    app_client: httpx.AsyncClient, db_session: AsyncSession, settings: Settings
) -> None:
    """WHEN el mismo cliente hace login y refresh THEN la cookie viaja sola."""
    _clinic, user = await _usuario(db_session)

    await _post_login(app_client, user.email)
    respuesta = await app_client.post("/api/auth/refresh")

    assert respuesta.status_code == 200
    assert app_client.cookies.get(refresh_cookie_name(settings))


async def test_password_incorrecta_y_email_inexistente_son_indistinguibles(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """WHEN falla la clave o el email THEN mismo 401 y mismo detalle."""
    _clinic, user = await _usuario(db_session)

    mala_clave = await _post_login(app_client, user.email, "otra-clave-ficticia-999")
    inexistente = await _post_login(app_client, "nadie.ficticio@example.com")

    assert mala_clave.status_code == inexistente.status_code == 401
    assert mala_clave.json() == inexistente.json()


async def test_usuario_inactivo_no_obtiene_sesion(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """WHEN `active=false` THEN 401 genérico y sin cookie de refresh."""
    _clinic, user = await _usuario(db_session, active=False)

    response = await _post_login(app_client, user.email)

    assert response.status_code == 401
    assert "set-cookie" not in {k.lower() for k in response.headers}


async def test_email_ambiguo_entre_clinicas_no_autentica(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """WHEN el email existe en dos clínicas THEN 401 (no elige tenant al azar)."""
    email = unique_email("staff.ambiguo")
    await _usuario(db_session, email=email)
    await _usuario(db_session, email=email)

    response = await _post_login(app_client, email)

    assert response.status_code == 401


async def test_campo_extra_en_el_body_da_422(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """WHEN el body trae un campo no declarado THEN 422 (`extra='forbid'`)."""
    _clinic, user = await _usuario(db_session)

    response = await _post_login(app_client, user.email, campo_fantasma=1)

    assert response.status_code == 422


async def test_login_fallido_queda_auditado_sin_pii(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """WHEN falla la clave THEN hay `login_failed` sin email ni contraseña."""
    _clinic, user = await _usuario(db_session)

    await _post_login(app_client, user.email, "otra-clave-ficticia-999")

    eventos = (
        (
            await db_session.execute(
                select(AuthEvent).where(AuthEvent.event == AuthEventType.LOGIN_FAILED)
            )
        )
        .scalars()
        .all()
    )
    assert eventos
    texto = " ".join(str(e.payload) + str(e.subject_hash) for e in eventos)
    assert user.email not in texto
    assert PASSWORD not in texto


async def test_sexto_intento_del_par_ip_email_da_429_sin_evaluar_credenciales(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """WHEN el par acumula 5 THEN el 6.º responde 429 con Retry-After."""
    _clinic, user = await _usuario(db_session)

    for _ in range(5):
        intento = await _post_login(app_client, user.email, "clave-equivocada-123")
        assert intento.status_code == 401
    sexto = await _post_login(app_client, user.email, PASSWORD)

    assert sexto.status_code == 429
    assert int(sexto.headers["Retry-After"]) > 0
    fila = (await db_session.execute(select(User).where(User.id == user.id))).scalar_one()
    assert fila.last_login_at is None


async def test_tope_por_ip_frena_emails_distintos(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WHEN una IP supera su tope THEN 429 aunque cada par siga debajo."""
    monkeypatch.setenv("AUTH_LOGIN_IP_RATE_LIMIT", "3/60s")
    monkeypatch.setenv("AUTH_LOGIN_RATE_LIMIT", "100/60s")
    await _usuario(db_session)

    for n in range(3):
        intento = await _post_login(app_client, f"nadie.{n}.ficticio@example.com")
        assert intento.status_code == 401
    cuarto = await _post_login(app_client, "nadie.final@example.com")

    assert cuarto.status_code == 429


async def test_clientes_con_ip_distinta_no_comparten_el_cupo_del_par(
    client_factory: Callable[..., httpx.AsyncClient], db_session: AsyncSession
) -> None:
    """WHEN dos IP prueban el mismo email THEN cada una tiene su propio cupo."""
    _clinic, user = await _usuario(db_session)
    uno = client_factory("10.10.10.1")
    dos = client_factory("10.10.10.2")
    try:
        for _ in range(5):
            assert (
                await uno.post(
                    "/api/auth/login",
                    json={"email": user.email, "password": "clave-equivocada-123"},
                )
            ).status_code == 401
        assert (
            await uno.post(
                "/api/auth/login",
                json={"email": user.email, "password": "clave-equivocada-123"},
            )
        ).status_code == 429
        assert (
            await dos.post(
                "/api/auth/login",
                json={"email": user.email, "password": PASSWORD},
            )
        ).status_code == 200
    finally:
        await uno.aclose()
        await dos.aclose()


async def test_rehash_perezoso_actualiza_parametros_viejos(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """WHEN el hash es legado THEN el login lo rehashea y la misma clave entra."""
    viejo = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash(PASSWORD)
    _clinic, user = await _usuario(db_session, password_hash=viejo)

    response = await _post_login(app_client, user.email)

    assert response.status_code == 200
    fila = (await db_session.execute(select(User).where(User.id == user.id))).scalar_one()
    assert fila.password_hash != viejo
    assert not needs_rehash(fila.password_hash)
    assert verify_password(PASSWORD, fila.password_hash)
