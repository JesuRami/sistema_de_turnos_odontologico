"""Middlewares ASGI puros del borde HTTP (C-14, D1/D5).

Son ASGI "a mano" y no `BaseHTTPMiddleware`: no copian el cuerpo, no cortan el streaming del
export y no rompen los `ContextVar` (el `request_id` llega igual a los handlers, servicios y
logs). Orden de afuera hacia adentro (lo fija `app.main.create_app`):

1. `RequestContextMiddleware`: request-id, log de acceso con la plantilla de la ruta y red de
   contención de excepciones no manejadas (500 uniforme, sin traza).
2. `SecurityHeadersMiddleware`: headers seguros en toda respuesta.
3. `TrustedHostMiddleware`: `Host` dentro de `ALLOWED_HOSTS`.
4. CORS (Starlette) y 5. `GlobalRateLimitMiddleware` (Redis con degradación a memoria).
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable, MutableMapping
from typing import Any

from app.core.logs import clinic_id_var, request_id_var

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

REQUEST_ID_HEADER = "x-request-id"
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
# Rutas de infraestructura: sin log de acceso ni rate-limit (las golpea el healthcheck).
QUIET_PATHS = frozenset({"/health", "/ready"})
# Documentación interactiva (solo fuera de prod): necesita scripts/estilos de su CDN.
_DOCS_PREFIXES = ("/docs", "/redoc", "/openapi.json")
# C-15 (D4): toda respuesta clínica, también un error, es `no-store` (datos de salud).
_CLINICAL_PATH_RE = re.compile(
    r"^/api/(clinical-records/|odontogram/|patients/[^/]+/clinical-record/?$)"
)


def is_clinical_path(path: str) -> bool:
    """Ruta de la historia clínica (ficha, anamnesis, odontograma, evoluciones, adjuntos...)."""
    return _CLINICAL_PATH_RE.match(path) is not None


access_logger = logging.getLogger("http.access")
error_logger = logging.getLogger("http.error")


def _header(scope: Scope, name: bytes) -> str | None:
    for clave, valor in scope.get("headers", ()):
        if clave == name:
            try:
                return str(valor.decode("latin-1"))
            except UnicodeDecodeError:
                return None
    return None


def _encode_headers(headers: Iterable[tuple[str, str]]) -> list[tuple[bytes, bytes]]:
    return [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers]


async def send_json(
    send: Send, status: int, body: dict[str, Any], headers: Iterable[tuple[str, str]] = ()
) -> None:
    """Respuesta JSON mínima desde un middleware (sin pasar por la app)."""
    cuerpo = json.dumps(body, ensure_ascii=False).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": _encode_headers(
                [
                    ("content-type", "application/json"),
                    ("content-length", str(len(cuerpo))),
                    *headers,
                ]
            ),
        }
    )
    await send({"type": "http.response.body", "body": cuerpo})


def new_request_id(incoming: str | None) -> str:
    """Respeta el id entrante si es seguro de loguear; si no, genera uno nuevo."""
    if incoming is not None and _REQUEST_ID_RE.match(incoming):
        return incoming
    return uuid.uuid4().hex


def route_template(scope: Scope) -> str:
    """Plantilla de la ruta resuelta (`/api/manage/{token}`), nunca el path real."""
    route = scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path:
        return path
    return "<unmatched>"


# --------------------------------------------------------------------------- headers seguros


def security_headers(*, hsts_seconds: int, path: str = "") -> list[tuple[str, str]]:
    """Headers de seguridad de la API (D1). La API solo sirve JSON/CSV/ZIP: CSP cerrada."""
    headers = [
        ("x-content-type-options", "nosniff"),
        ("x-frame-options", "DENY"),
        ("referrer-policy", "strict-origin-when-cross-origin"),
        ("permissions-policy", "camera=(), microphone=(), geolocation=(), payment=()"),
        ("cross-origin-opener-policy", "same-origin"),
        ("cross-origin-resource-policy", "same-site"),
    ]
    if not path.startswith(_DOCS_PREFIXES):
        headers.append(("content-security-policy", "default-src 'none'; frame-ancestors 'none'"))
    if hsts_seconds > 0:
        headers.append(("strict-transport-security", f"max-age={hsts_seconds}; includeSubDomains"))
    if is_clinical_path(path):
        headers.append(("cache-control", "no-store"))
    return headers


class SecurityHeadersMiddleware:
    """Agrega los headers seguros sin pisar los que la ruta ya fijó (p. ej. `no-referrer`)."""

    def __init__(self, app: ASGIApp, *, hsts_seconds: int = 0) -> None:
        self.app = app
        self.hsts_seconds = hsts_seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        extra = security_headers(hsts_seconds=self.hsts_seconds, path=scope.get("path", ""))

        async def _send(message: Message) -> None:
            if message["type"] == "http.response.start":
                actuales = list(message.get("headers", []))
                presentes = {k.lower() for k, _ in actuales}
                for clave, valor in _encode_headers(extra):
                    if clave not in presentes:
                        actuales.append((clave, valor))
                message["headers"] = actuales
            await send(message)

        await self.app(scope, receive, _send)


# --------------------------------------------------------------------------- hosts confiables


class TrustedHostMiddleware:
    """`Host` dentro de `ALLOWED_HOSTS` (`*.dominio` admite subdominios); si no, 400 JSON."""

    def __init__(self, app: ASGIApp, *, allowed_hosts: Iterable[str]) -> None:
        self.app = app
        hosts = [h.strip().lower() for h in allowed_hosts if h.strip()]
        self.allow_any = "*" in hosts
        self.exact = {h for h in hosts if not h.startswith("*.")}
        self.suffixes = tuple(h[1:] for h in hosts if h.startswith("*."))

    def _ok(self, host: str) -> bool:
        if self.allow_any:
            return True
        nombre = host.lower()
        if nombre.startswith("["):  # IPv6 literal con puerto
            nombre = nombre.split("]", 1)[0] + "]"
        else:
            nombre = nombre.rsplit(":", 1)[0] if nombre.count(":") == 1 else nombre
        return nombre in self.exact or (bool(self.suffixes) and nombre.endswith(self.suffixes))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or scope.get("path") in QUIET_PATHS:
            await self.app(scope, receive, send)
            return
        host = _header(scope, b"host") or ""
        if not self._ok(host):
            await send_json(send, 400, {"detail": "invalid_host"})
            return
        await self.app(scope, receive, send)


# --------------------------------------------------------------------------- contexto + 500


class RequestContextMiddleware:
    """Request-id, log de acceso sin PII y 500 uniforme para lo no manejado (D1/D3).

    Las excepciones que llegan hasta acá ya no tienen handler (los de dominio, validación y
    base de datos se resuelven adentro, en `ExceptionMiddleware`). Se contestan acá y no en el
    `ServerErrorMiddleware` de Starlette porque ese corre por fuera de este middleware: el
    `request_id` ya se habría limpiado y la respuesta saldría sin `X-Request-ID`.
    """

    def __init__(self, app: ASGIApp, *, hsts_seconds: int = 0) -> None:
        self.app = app
        self.hsts_seconds = hsts_seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = new_request_id(_header(scope, b"x-request-id"))
        scope.setdefault("state", {})["request_id"] = request_id
        token_rid = request_id_var.set(request_id)
        token_cid = clinic_id_var.set(None)
        inicio = time.perf_counter()
        estado = {"status": 500, "started": False}

        async def _send(message: Message) -> None:
            if message["type"] == "http.response.start":
                estado["status"] = int(message["status"])
                estado["started"] = True
                headers = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k.lower() != REQUEST_ID_HEADER.encode()
                ]
                headers.append((REQUEST_ID_HEADER.encode(), request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, _send)
        except Exception as exc:  # noqa: BLE001 - red de contención: nunca traza al cliente
            error_logger.error(
                "unhandled_error type=%s route=%s",
                type(exc).__name__,
                route_template(scope),
                exc_info=exc,
            )
            if not estado["started"]:
                estado["status"] = 500
                await send_json(
                    send,
                    500,
                    {"detail": "internal_error", "request_id": request_id},
                    [
                        (REQUEST_ID_HEADER, request_id),
                        ("cache-control", "no-store"),
                        *security_headers(hsts_seconds=self.hsts_seconds),
                    ],
                )
        finally:
            if scope.get("path") not in QUIET_PATHS:
                access_logger.info(
                    "request",
                    extra={
                        "method": scope.get("method", ""),
                        "route": route_template(scope),
                        "status": estado["status"],
                        "duration_ms": round((time.perf_counter() - inicio) * 1000, 1),
                    },
                )
            clinic_id_var.reset(token_cid)
            request_id_var.reset(token_rid)


# --------------------------------------------------------------------------- rate-limit global

_HIT_LUA = """
local actual = redis.call('INCR', KEYS[1])
if actual == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {actual, ttl}
"""

_DEGRADED_FOR_S = 30.0


class GlobalRateLimitMiddleware:
    """Tope global por IP, compartido entre procesos vía Redis (D5).

    Si Redis no responde, por `_DEGRADED_FOR_S` segundos cuenta en memoria del proceso
    (fail-open a propósito: es protección de disponibilidad; los cupos que protegen datos,
    login y reserva, siguen fail-closed en sus propias dependencias).
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_requests: int,
        window_s: float,
        exempt_paths: Iterable[str] = (),
        redis_getter: Callable[[Scope], Any] | None = None,
    ) -> None:
        self.app = app
        self.max_requests = max_requests
        self.window_s = window_s
        self.exempt = frozenset(QUIET_PATHS | set(exempt_paths))
        self._redis_getter = redis_getter or _redis_from_app
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._degraded_until = 0.0

    def _memory_hit(self, key: str) -> tuple[bool, int]:
        ahora = time.monotonic()
        desde = ahora - self.window_s
        hits = [t for t in self._hits[key] if t > desde]
        if len(hits) >= self.max_requests:
            self._hits[key] = hits
            reintento = int(hits[0] + self.window_s - ahora) + 1
            return False, max(reintento, 1)
        hits.append(ahora)
        self._hits[key] = hits
        return True, 0

    async def _redis_hit(self, redis: Any, ip: str) -> tuple[bool, int]:
        actual, ttl = await redis.eval(_HIT_LUA, 1, f"rl:global:ip:{ip}", str(int(self.window_s)))
        usado = int(actual)
        restante = int(ttl) if int(ttl) > 0 else int(self.window_s)
        return usado <= self.max_requests, restante

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") in self.exempt:
            await self.app(scope, receive, send)
            return
        cliente = scope.get("client")
        ip = cliente[0] if cliente else "unknown"
        permitido, reintento = True, 0
        redis = self._redis_getter(scope)
        if redis is not None and time.monotonic() >= self._degraded_until:
            try:
                permitido, reintento = await self._redis_hit(redis, ip)
            except Exception as exc:  # noqa: BLE001 - Redis caído: degradar, no tirar el request
                self._degraded_until = time.monotonic() + _DEGRADED_FOR_S
                logging.getLogger("http.rate_limit").warning(
                    "rate_limit_degraded backend=memory error=%s", type(exc).__name__
                )
                permitido, reintento = self._memory_hit(ip)
        else:
            permitido, reintento = self._memory_hit(ip)
        if not permitido:
            await send_json(
                send, 429, {"detail": "rate_limited"}, [("retry-after", str(max(reintento, 1)))]
            )
            return
        await self.app(scope, receive, send)


def _redis_from_app(scope: Scope) -> Any:
    app = scope.get("app")
    state = getattr(app, "state", None)
    return getattr(state, "redis", None)
