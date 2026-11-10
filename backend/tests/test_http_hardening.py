"""Borde HTTP endurecido de la app real (C-14, D1/D3/D6). Sin base ni Redis: todo se resuelve
antes de tocar servicios (validación, headers, ruteo, bearer, mapeo de errores).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from app.core.settings import Settings
from app.main import create_app
from fastapi import FastAPI
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError

URL = "http://test"


def _settings(**cambios: Any) -> Settings:
    return Settings().model_copy(update=cambios)  # type: ignore[call-arg]


async def _get(app: FastAPI, path: str, **kwargs: Any) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=URL, timeout=5.0) as client:
        return await client.get(path, **kwargs)


async def _request(app: FastAPI, method: str, path: str, **kwargs: Any) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=URL, timeout=5.0) as client:
        return await client.request(method, path, **kwargs)


# --------------------------------------------------------------------------- headers + request-id


async def test_toda_respuesta_lleva_headers_seguros_y_request_id() -> None:
    respuesta = await _get(create_app(), "/health")

    assert respuesta.status_code == 200
    assert respuesta.headers["x-content-type-options"] == "nosniff"
    assert respuesta.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in respuesta.headers["content-security-policy"]
    assert len(respuesta.headers["x-request-id"]) == 32
    # Fuera de prod no hay HSTS (romperia otros proyectos en localhost).
    assert "strict-transport-security" not in respuesta.headers


async def test_request_id_entrante_se_propaga() -> None:
    respuesta = await _get(create_app(), "/health", headers={"X-Request-ID": "req-front-00000001"})
    assert respuesta.headers["x-request-id"] == "req-front-00000001"


async def test_las_rutas_con_token_conservan_no_referrer_y_no_store() -> None:
    respuesta = await _get(create_app(), "/api/manage/token-que-no-existe-xxxxxxxx")

    assert respuesta.headers["referrer-policy"] == "no-referrer"
    assert respuesta.headers["cache-control"] == "no-store"


async def test_ruta_inexistente_da_404_con_codigo_corto() -> None:
    respuesta = await _get(create_app(), "/api/no-existe")

    assert respuesta.status_code == 404
    assert respuesta.json() == {"detail": "not_found"}
    assert respuesta.headers["x-content-type-options"] == "nosniff"


async def test_metodo_no_permitido_da_405_con_codigo_corto() -> None:
    respuesta = await _request(create_app(), "PUT", "/health")
    assert (respuesta.status_code, respuesta.json()) == (405, {"detail": "method_not_allowed"})


# --------------------------------------------------------------------------- hosts / CORS / docs


async def test_host_fuera_de_allowed_hosts_da_400() -> None:
    app = create_app(_settings(ALLOWED_HOSTS="turnos.example.com"))
    respuesta = await _get(app, "/api/no-existe")
    assert (respuesta.status_code, respuesta.json()) == (400, {"detail": "invalid_host"})


async def test_healthcheck_pasa_aunque_el_host_no_este_permitido() -> None:
    app = create_app(_settings(ALLOWED_HOSTS="turnos.example.com"))
    assert (await _get(app, "/health")).status_code == 200


async def test_cors_preflight_solo_admite_headers_declarados() -> None:
    app = create_app(_settings(CORS_ORIGINS="http://localhost:5173"))
    base = {"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"}
    permitido = await _request(
        app,
        "OPTIONS",
        "/api/auth/login",
        headers={**base, "Access-Control-Request-Headers": "content-type,x-request-id"},
    )
    raro = await _request(
        app,
        "OPTIONS",
        "/api/auth/login",
        headers={**base, "Access-Control-Request-Headers": "x-header-inventado"},
    )
    otro_origen = await _request(
        app,
        "OPTIONS",
        "/api/auth/login",
        headers={**base, "Origin": "https://malicioso.example.net"},
    )

    assert permitido.status_code == 200
    assert permitido.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert raro.status_code == 400
    assert "access-control-allow-origin" not in otro_origen.headers


async def test_en_prod_no_se_publica_el_esquema_ni_la_consola() -> None:
    app = create_app(
        _settings(
            ENV="prod",
            ALLOWED_HOSTS="test",
            CORS_ORIGINS="https://turnos.example.com",
            FRONTEND_PUBLIC_URL="https://turnos.example.com",
        )
    )
    for path in ("/openapi.json", "/docs", "/redoc"):
        assert (await _get(app, path)).status_code == 404
    hsts = (await _get(app, "/health")).headers["strict-transport-security"]
    assert hsts.startswith("max-age=")


# --------------------------------------------------------------------------- validación sin eco


async def test_422_del_personal_no_ecoa_el_input() -> None:
    """Regla 13: el 422 de FastAPI por defecto devuelve `input` (acá, un email y una clave)."""
    respuesta = await _request(
        create_app(),
        "POST",
        "/api/auth/login",
        json={
            "email": "persona.ficticia@example.com",
            "password": "clave-ficticia-123",
            "campo_fantasma": "valor-que-no-debe-volver",
        },
    )

    assert respuesta.status_code == 422
    texto = respuesta.text
    assert "persona.ficticia" not in texto
    assert "valor-que-no-debe-volver" not in texto
    for error in respuesta.json()["detail"]:
        assert set(error) <= {"loc", "msg", "type"}


@pytest.mark.integration
async def test_422_de_la_oferta_publica_solo_informa_campos(app_client: httpx.AsyncClient) -> None:
    """`/api/waitlist-offer/` entra en los bordes públicos (antes solo booking y manage)."""
    respuesta = await app_client.post(
        "/api/waitlist-offer/w1.token-ficticio-xxxxxxxxxxxx/decline",
        json={"leave_list": "no-es-bool", "extra": "+5491155550111"},
    )

    assert respuesta.status_code == 422
    assert respuesta.json()["detail"] == "invalid_request"
    assert "5491155550111" not in respuesta.text
    assert respuesta.headers["cache-control"] == "no-store"


# --------------------------------------------------------------------------- bearer estricto (D6)


@pytest.mark.parametrize(
    "authorization",
    [
        "Bearer " + "a" * 5000,
        "Bearer no-es-un-jwt",
        "Bearer a.b.c d",
        "Basic dXN1YXJpbzpjbGF2ZQ==",
        "Bearer",
    ],
)
async def test_bearer_malformado_es_401_con_desafio(authorization: str) -> None:
    respuesta = await _get(create_app(), "/api/auth/me", headers={"Authorization": authorization})

    assert respuesta.status_code == 401
    assert respuesta.json() == {"detail": "token_invalid"}
    assert respuesta.headers["www-authenticate"] == "Bearer"


# --------------------------------------------------------------------------- errores (D3)


class _Orig(Exception):
    def __init__(self, sqlstate: str | None) -> None:
        super().__init__("detalle del driver con +5491155550111")
        self.sqlstate = sqlstate


def _app_que_falla(exc: BaseException) -> FastAPI:
    app = create_app()

    @app.get("/api/_test/falla")
    async def _falla() -> None:
        raise exc

    return app


@pytest.mark.parametrize(
    ("exc", "estado", "detalle", "retry"),
    [
        (DBAPIError("UPDATE x", {}, _Orig("40P01")), 409, "concurrent_update", "1"),
        (DBAPIError("UPDATE x", {}, _Orig("40001")), 409, "concurrent_update", "1"),
        (DBAPIError("SELECT 1", {}, _Orig("55P03")), 409, "concurrent_update", "1"),
        (DBAPIError("SELECT 1", {}, _Orig("57014")), 503, "db_timeout", "5"),
        (IntegrityError("INSERT x", {}, _Orig("23505")), 409, "conflict", None),
        (OperationalError("SELECT 1", {}, _Orig("08006")), 503, "db_unavailable", "5"),
        (DBAPIError("SELECT 1", {}, _Orig("XX000")), 500, "internal_error", None),
    ],
)
async def test_errores_de_postgres_se_traducen_sin_filtrar_el_driver(
    exc: BaseException, estado: int, detalle: str, retry: str | None
) -> None:
    respuesta = await _get(_app_que_falla(exc), "/api/_test/falla")

    assert respuesta.status_code == estado
    assert respuesta.json()["detail"] == detalle
    assert respuesta.headers.get("retry-after") == retry
    assert "5491155550111" not in respuesta.text
    if estado >= 500:
        assert respuesta.json()["request_id"] == respuesta.headers["x-request-id"]


async def test_excepcion_inesperada_da_500_uniforme(caplog: pytest.LogCaptureFixture) -> None:
    respuesta = await _get(_app_que_falla(RuntimeError("tel +5491155550111")), "/api/_test/falla")

    assert respuesta.status_code == 500
    assert respuesta.json() == {
        "detail": "internal_error",
        "request_id": respuesta.headers["x-request-id"],
    }
    assert "Traceback" not in respuesta.text
    assert any("unhandled_error" in r.getMessage() for r in caplog.records)


# --------------------------------------------------------------------------- rate-limit global


async def test_rate_limit_global_responde_rate_limited_con_retry_after() -> None:
    app = create_app(_settings(BOOKING_RATE_LIMIT="2/minute", GLOBAL_RATE_LIMIT_BACKEND="memory"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=URL, timeout=5.0) as client:
        for _ in range(2):
            assert (await client.get("/openapi.json")).status_code == 200
        respuesta = await client.get("/openapi.json")
        salud = await client.get("/health")

    assert respuesta.status_code == 429
    assert respuesta.json() == {"detail": "rate_limited"}
    assert int(respuesta.headers["retry-after"]) >= 1
    assert salud.status_code == 200
