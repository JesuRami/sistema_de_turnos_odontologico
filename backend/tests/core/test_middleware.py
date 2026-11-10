"""Middlewares ASGI del borde (C-14, D1/D3/D5) contra una app ASGI mínima. Puro: sin red ni base.

Síncronos con `asyncio.run` a propósito: corren igual con o sin `pytest-asyncio`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import pytest
from app.core.logs import request_id_var
from app.core.middleware import (
    GlobalRateLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
    TrustedHostMiddleware,
    new_request_id,
)


class Ruta:
    def __init__(self, path: str) -> None:
        self.path = path


def app_ok(*, route: str | None = None, headers: list[tuple[bytes, bytes]] | None = None) -> Any:
    async def _app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if route is not None:
            scope["route"] = Ruta(route)
        scope.setdefault("seen_request_id", request_id_var.get())
        await send({"type": "http.response.start", "status": 200, "headers": list(headers or [])})
        await send({"type": "http.response.body", "body": b"{}"})

    return _app


def app_que_explota() -> Any:
    async def _app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        raise RuntimeError("Key (phone_e164)=(+5491155550111) ya existe")

    return _app


def llamar(
    app: Any,
    path: str = "/api/x",
    headers: list[tuple[bytes, bytes]] | None = None,
    client: tuple[str, int] = ("10.0.0.1", 1234),
) -> tuple[int, dict[str, str], bytes, dict[str, Any]]:
    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": headers or [(b"host", b"api.example.com")],
        "client": client,
    }
    mensajes: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        mensajes.append(message)

    asyncio.run(app(scope, receive, send))
    inicio = next(m for m in mensajes if m["type"] == "http.response.start")
    cuerpo = b"".join(m.get("body", b"") for m in mensajes if m["type"] == "http.response.body")
    hdrs = {k.decode(): v.decode() for k, v in inicio["headers"]}
    return inicio["status"], hdrs, cuerpo, scope


# --------------------------------------------------------------------------- request-id


def test_request_id_entrante_valido_se_respeta_y_se_devuelve() -> None:
    estado, headers, _, scope = llamar(
        RequestContextMiddleware(app_ok()),
        headers=[(b"host", b"api.example.com"), (b"x-request-id", b"abcdef12-req")],
    )
    assert estado == 200
    assert headers["x-request-id"] == "abcdef12-req"
    assert scope["seen_request_id"] == "abcdef12-req"


@pytest.mark.parametrize("entrante", [None, "corto", "con espacios no", "x" * 65, "<script>"])
def test_request_id_invalido_o_ausente_se_regenera(entrante: str | None) -> None:
    generado = new_request_id(entrante)
    assert generado != entrante
    assert len(generado) == 32


def test_el_contexto_se_limpia_al_terminar() -> None:
    llamar(RequestContextMiddleware(app_ok()))
    assert request_id_var.get() is None


def test_log_de_acceso_usa_la_plantilla_de_la_ruta_y_no_el_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="http.access")
    llamar(
        RequestContextMiddleware(app_ok(route="/api/manage/{token}")),
        path="/api/manage/m1.token-secreto-del-paciente",
    )
    registro = next(r for r in caplog.records if r.name == "http.access")

    assert registro.route == "/api/manage/{token}"  # type: ignore[attr-defined]
    assert "token-secreto" not in caplog.text
    assert registro.status == 200  # type: ignore[attr-defined]


def test_health_no_genera_log_de_acceso(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="http.access")
    llamar(RequestContextMiddleware(app_ok()), path="/health")
    assert not [r for r in caplog.records if r.name == "http.access"]


def test_excepcion_no_manejada_da_500_uniforme_sin_traza() -> None:
    estado, headers, cuerpo, _ = llamar(RequestContextMiddleware(app_que_explota()))
    datos = json.loads(cuerpo)

    assert estado == 500
    assert datos == {"detail": "internal_error", "request_id": headers["x-request-id"]}
    assert headers["cache-control"] == "no-store"
    assert headers["x-content-type-options"] == "nosniff"
    assert b"Traceback" not in cuerpo and b"5491155550111" not in cuerpo


# --------------------------------------------------------------------------- headers seguros


def test_headers_seguros_en_toda_respuesta() -> None:
    _, headers, _, _ = llamar(SecurityHeadersMiddleware(app_ok()))

    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert headers["cross-origin-opener-policy"] == "same-origin"
    assert "strict-transport-security" not in headers


def test_hsts_solo_si_se_configura() -> None:
    _, headers, _, _ = llamar(SecurityHeadersMiddleware(app_ok(), hsts_seconds=31_536_000))
    assert headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"


def test_no_pisa_el_referrer_policy_de_las_rutas_con_token() -> None:
    propio = [(b"referrer-policy", b"no-referrer")]
    _, headers, _, _ = llamar(SecurityHeadersMiddleware(app_ok(headers=propio)))
    assert headers["referrer-policy"] == "no-referrer"


def test_docs_quedan_fuera_de_la_csp_estricta() -> None:
    _, headers, _, _ = llamar(SecurityHeadersMiddleware(app_ok()), path="/docs")
    assert "content-security-policy" not in headers


# --------------------------------------------------------------------------- hosts


@pytest.mark.parametrize(
    ("host", "permitido"),
    [
        ("turnos.example.com", True),
        ("turnos.example.com:443", True),
        ("clinica.app.example.com", True),
        ("app.example.com", False),
        ("malicioso.example.net", False),
        ("", False),
    ],
)
def test_trusted_host(host: str, permitido: bool) -> None:
    app = TrustedHostMiddleware(app_ok(), allowed_hosts=["turnos.example.com", "*.app.example.com"])
    estado, _, cuerpo, _ = llamar(app, headers=[(b"host", host.encode())])
    if permitido:
        assert estado == 200
    else:
        assert (estado, json.loads(cuerpo)) == (400, {"detail": "invalid_host"})


def test_trusted_host_no_corta_el_healthcheck() -> None:
    app = TrustedHostMiddleware(app_ok(), allowed_hosts=["turnos.example.com"])
    estado, *_ = llamar(app, path="/ready", headers=[(b"host", b"localhost:8000")])
    assert estado == 200


# --------------------------------------------------------------------------- rate-limit


def _sin_redis(_: object) -> None:
    return None


def test_rate_limit_en_memoria_responde_429_con_retry_after() -> None:
    app = GlobalRateLimitMiddleware(app_ok(), max_requests=2, window_s=60, redis_getter=_sin_redis)
    assert llamar(app)[0] == 200
    assert llamar(app)[0] == 200
    estado, headers, cuerpo, _ = llamar(app)

    assert estado == 429
    assert json.loads(cuerpo) == {"detail": "rate_limited"}
    assert int(headers["retry-after"]) >= 1


def test_rate_limit_es_por_ip() -> None:
    app = GlobalRateLimitMiddleware(app_ok(), max_requests=1, window_s=60, redis_getter=_sin_redis)
    assert llamar(app, client=("10.0.0.1", 1))[0] == 200
    assert llamar(app, client=("10.0.0.2", 1))[0] == 200
    assert llamar(app, client=("10.0.0.1", 1))[0] == 429


def test_rate_limit_exime_salud_y_webhook() -> None:
    app = GlobalRateLimitMiddleware(
        app_ok(),
        max_requests=1,
        window_s=60,
        exempt_paths=("/webhooks/whatsapp",),
        redis_getter=_sin_redis,
    )
    for _ in range(3):
        assert llamar(app, path="/health")[0] == 200
        assert llamar(app, path="/webhooks/whatsapp")[0] == 200


class RedisCaido:
    async def eval(self, *args: object) -> object:
        raise ConnectionError("redis no responde")


def test_redis_caido_degrada_a_memoria_sin_tirar_el_request(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="http.rate_limit")
    app = GlobalRateLimitMiddleware(
        app_ok(), max_requests=1, window_s=60, redis_getter=lambda _: RedisCaido()
    )

    assert llamar(app)[0] == 200
    assert llamar(app)[0] == 429
    avisos = [r for r in caplog.records if "rate_limit_degraded" in r.getMessage()]
    assert len(avisos) == 1  # una vez por apertura del circuito, no por request


class RedisFalso:
    """Ventana fija compartida: dos middlewares (dos procesos) ven el mismo contador."""

    def __init__(self) -> None:
        self.contador: dict[str, int] = {}

    async def eval(self, _lua: str, _n: int, clave: str, ventana: str) -> list[int]:
        self.contador[clave] = self.contador.get(clave, 0) + 1
        return [self.contador[clave], int(ventana)]


def test_el_contador_redis_se_comparte_entre_procesos() -> None:
    redis = RedisFalso()
    proceso_a = GlobalRateLimitMiddleware(
        app_ok(), max_requests=2, window_s=60, redis_getter=lambda _: redis
    )
    proceso_b = GlobalRateLimitMiddleware(
        app_ok(), max_requests=2, window_s=60, redis_getter=lambda _: redis
    )
    assert llamar(proceso_a)[0] == 200
    assert llamar(proceso_b)[0] == 200
    estado, headers, _, _ = llamar(proceso_a)
    assert (estado, headers["retry-after"]) == (429, "60")
