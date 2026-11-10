"""Excepciones de dominio + handlers con envolvente uniforme.

C-14 (D3) agrega:

- Errores de Postgres traducidos por SQLSTATE: concurrencia (`40001`, `40P01`, `55P03`) →
  `409 concurrent_update` + `Retry-After`; `57014` (statement timeout) → `503 db_timeout`;
  integridad no manejada (`23xxx`) → `409 conflict`; conexión → `503 db_unavailable`.
- El 422 de las rutas del personal ya no ecoa `input`/`ctx` (regla 13: el cuerpo de un alta de
  paciente lleva nombre, teléfono y DNI); `/api/waitlist-offer/` se suma a los bordes públicos.
- 404/405 de ruteo con código corto (`not_found`, `method_not_allowed`).
- Todo 5xx lleva `request_id` para cruzarlo con los logs; nunca la traza.

Lo que no tiene handler acá lo contesta `RequestContextMiddleware` (500 `internal_error`).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from sqlalchemy.exc import DBAPIError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logs import request_id_var

logger = logging.getLogger("http.error")

# La reserva, la gestión y la oferta públicas son anónimas y su cuerpo puede llevar datos
# personales: el 422 por defecto de FastAPI ecoa `input` (regla 13), así que bajo estos prefijos
# solo se informan nombres de campo.
_PUBLIC_PREFIXES = ("/api/booking/", "/api/manage/", "/api/waitlist-offer/")
_FIELD_RE = re.compile(r"^[A-Za-z0-9_.\[\]]{1,64}$")
# Las rutas con token en el path llevan datos del turno o de la oferta: ninguna respuesta (tampoco
# un error) se cachea ni filtra su URL por `Referer` (C-08, D2; C-12).
_PRIVATE_PREFIXES = ("/api/manage/", "/api/waitlist-offer/")
PRIVATE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}

# SQLSTATE de Postgres (apéndice "PostgreSQL Error Codes" del manual 15).
_CONCURRENCY = {"40001", "40P01", "55P03"}
_STATEMENT_TIMEOUT = "57014"
_CONNECTION_CLASS = "08"
_INTEGRITY_CLASS = "23"
_VALIDATION_KEYS = ("loc", "msg", "type")


class DomainError(Exception):
    """Error de dominio con código HTTP, detalle público, headers y campos extra opcionales.

    `extra` agrega claves públicas al cuerpo (p. ej. ids en conflicto); nunca PII.
    """

    def __init__(
        self,
        status_code: int,
        detail: str,
        headers: dict[str, str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.headers = headers
        self.extra = extra


def _public_fields(exc: RequestValidationError) -> list[str]:
    """Rutas de campo del error, sin valores; nombres raros se enmascaran."""
    campos: list[str] = []
    for error in exc.errors():
        ruta = ".".join(str(parte) for parte in error["loc"][1:])
        campo = ruta if _FIELD_RE.match(ruta) else "?"
        if campo not in campos:
            campos.append(campo)
    return campos


def staff_validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    """Errores de FastAPI sin `input`, `ctx` ni `url` (regla 13); `msg` sin valores interpolados.

    Los mensajes de Pydantic v2 no interpolan el valor recibido salvo en `literal_error`/`enum`
    (lista de opciones válidas, no del input) y en los `ValueError` propios, que el proyecto
    escribe sin datos personales.
    """
    limpios: list[dict[str, Any]] = []
    for error in exc.errors():
        limpio = {clave: error[clave] for clave in _VALIDATION_KEYS if clave in error}
        limpio["loc"] = [str(parte) for parte in limpio.get("loc", ())]
        limpios.append(limpio)
    return limpios


def _headers_for(request: Request, headers: dict[str, str] | None) -> dict[str, str] | None:
    if not request.url.path.startswith(_PRIVATE_PREFIXES):
        return headers
    return {**PRIVATE_HEADERS, **(headers or {})}


def sqlstate_of(exc: BaseException) -> str | None:
    """SQLSTATE de un error de SQLAlchemy/asyncpg (el adaptador lo expone de varias formas)."""
    candidatos: list[object] = [exc]
    orig = getattr(exc, "orig", None)
    if orig is not None:
        candidatos += [orig, getattr(orig, "__cause__", None)]
    for candidato in candidatos:
        for atributo in ("sqlstate", "pgcode"):
            valor = getattr(candidato, atributo, None)
            if isinstance(valor, str) and len(valor) == 5:
                return valor
    return None


def map_db_error(exc: BaseException) -> tuple[int, str, dict[str, str]] | None:
    """`(status, detail, headers)` para un error de base de datos conocido; `None` = 500."""
    estado = sqlstate_of(exc)
    if estado in _CONCURRENCY:
        return 409, "concurrent_update", {"Retry-After": "1"}
    if estado == _STATEMENT_TIMEOUT:
        return 503, "db_timeout", {"Retry-After": "5"}
    if estado is not None and estado.startswith(_INTEGRITY_CLASS):
        return 409, "conflict", {}
    if estado is not None and estado.startswith(_CONNECTION_CLASS):
        return 503, "db_unavailable", {"Retry-After": "5"}
    if estado is None and getattr(exc, "connection_invalidated", False):
        return 503, "db_unavailable", {"Retry-After": "5"}
    return None


def _with_request_id(content: dict[str, Any], status: int) -> dict[str, Any]:
    if status >= 500:
        content["request_id"] = request_id_var.get()
    return content


_HTTP_CODES = {404: "not_found", 405: "method_not_allowed"}


def register_exception_handlers(app: FastAPI) -> None:
    """Registra handlers que devuelven siempre `{"detail": ...}`."""

    @app.exception_handler(DomainError)
    async def _domain_error(request: Request, exc: DomainError) -> JSONResponse:
        # Los 503 de dominio (`auth_unavailable`, `booking_unavailable`…) son contrato de C-03/
        # C-07/C-08 y no cambian de forma; el `X-Request-ID` igual viaja en el header.
        content: dict[str, Any] = {**(exc.extra or {}), "detail": exc.detail}
        return JSONResponse(
            status_code=exc.status_code,
            content=content,
            headers=_headers_for(request, exc.headers),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> Response:
        if request.url.path.startswith(_PUBLIC_PREFIXES):
            return JSONResponse(
                status_code=422,
                content={"detail": "invalid_request", "fields": _public_fields(exc)},
                headers=_headers_for(request, None),
            )
        return JSONResponse(status_code=422, content={"detail": staff_validation_errors(exc)})

    @app.exception_handler(DBAPIError)
    async def _db_error(request: Request, exc: DBAPIError) -> JSONResponse:
        mapeo = map_db_error(exc)
        if mapeo is None:
            logger.error(
                "unhandled_db_error sqlstate=%s type=%s",
                sqlstate_of(exc),
                type(exc.orig).__name__ if exc.orig is not None else type(exc).__name__,
                exc_info=exc,
            )
            return JSONResponse(
                status_code=500,
                content=_with_request_id({"detail": "internal_error"}, 500),
                headers=_headers_for(request, {"Cache-Control": "no-store"}),
            )
        status, detail, headers = mapeo
        # Sin el mensaje del driver: puede traer valores de la fila (teléfono, DNI).
        logger.warning("db_error_mapped sqlstate=%s detail=%s", sqlstate_of(exc), detail)
        return JSONResponse(
            status_code=status,
            content=_with_request_id({"detail": detail}, status),
            headers=_headers_for(request, headers),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = _HTTP_CODES.get(exc.status_code)
        if detail is None:
            detail = exc.detail if isinstance(exc.detail, str) else f"http_{exc.status_code}"
        headers = dict(exc.headers) if exc.headers else None
        return JSONResponse(
            status_code=exc.status_code,
            content=_with_request_id({"detail": detail}, exc.status_code),
            headers=_headers_for(request, headers),
        )
