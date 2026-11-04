"""Excepciones de dominio + handlers con envolvente uniforme."""

import re
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

# La reserva pública es anónima y su cuerpo lleva datos personales: el 422 por defecto de
# FastAPI ecoa `input` (regla 13), así que bajo este prefijo solo se informan nombres de campo.
_PUBLIC_PREFIX = "/api/booking/"
_FIELD_RE = re.compile(r"^[A-Za-z0-9_.\[\]]{1,64}$")


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


def register_exception_handlers(app: FastAPI) -> None:
    """Registra handlers que devuelven siempre `{"detail": ...}`."""

    @app.exception_handler(DomainError)
    async def _domain_error(request: Request, exc: DomainError) -> JSONResponse:
        _ = request
        content: dict[str, Any] = {**(exc.extra or {}), "detail": exc.detail}
        return JSONResponse(
            status_code=exc.status_code,
            content=content,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> Response:
        if request.url.path.startswith(_PUBLIC_PREFIX):
            return JSONResponse(
                status_code=422,
                content={"detail": "invalid_request", "fields": _public_fields(exc)},
            )
        return await request_validation_exception_handler(request, exc)
