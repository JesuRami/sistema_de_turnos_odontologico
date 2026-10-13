"""Excepciones de dominio + handlers con envolvente uniforme."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class DomainError(Exception):
    """Error de dominio con código HTTP y detalle público (sin trazas)."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def register_exception_handlers(app: FastAPI) -> None:
    """Registra handlers que devuelven siempre `{"detail": ...}`."""

    @app.exception_handler(DomainError)
    async def _domain_error(request: Request, exc: DomainError) -> JSONResponse:
        _ = request
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
