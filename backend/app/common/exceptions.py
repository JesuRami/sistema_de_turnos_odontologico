"""Excepciones de dominio + handlers con envolvente uniforme."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class DomainError(Exception):
    """Error de dominio con código HTTP, detalle público y headers opcionales."""

    def __init__(
        self,
        status_code: int,
        detail: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.headers = headers


def register_exception_handlers(app: FastAPI) -> None:
    """Registra handlers que devuelven siempre `{"detail": ...}`."""

    @app.exception_handler(DomainError)
    async def _domain_error(request: Request, exc: DomainError) -> JSONResponse:
        _ = request
        content: dict[str, Any] = {"detail": exc.detail}
        return JSONResponse(
            status_code=exc.status_code,
            content=content,
            headers=exc.headers,
        )
