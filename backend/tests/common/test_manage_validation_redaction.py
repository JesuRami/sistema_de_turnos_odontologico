"""Redacción del 422 en la superficie pública de gestión (C-08, regla 13).

`/api/manage/` transporta el token del paciente y el cuerpo puede traer datos
personales: el 422 solo informa nombres de campo, nunca `input` ni el token.
"""

from __future__ import annotations

from typing import Annotated

import httpx
import pytest
from app.common.exceptions import register_exception_handlers
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, StringConstraints

NOTE = "n" * 300
TOKEN = "token-sintetico-de-cuarenta-y-tres-caracteres-abcdefg"
PATH = f"/api/manage/{TOKEN}"


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]


def _app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.patch(PATH)
    async def _manage(body: _Body) -> dict[str, str]:
        return {"note": body.note}

    @app.post("/api/booking/{slug}/appointments")
    async def _booking(body: _Body) -> dict[str, str]:
        return {"note": body.note}

    return app


async def _patch(app: FastAPI, path: str, note: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.patch(path, json={"note": note})


async def _post(app: FastAPI, path: str, note: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(path, json={"note": note})


async def test_422_de_manage_no_ecoa_la_nota_ni_el_token() -> None:
    response = await _patch(_app(), PATH, NOTE)

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_request", "fields": ["note"]}
    assert NOTE not in response.text
    assert TOKEN not in response.text


async def test_422_de_booking_sigue_redactando() -> None:
    response = await _post(_app(), "/api/booking/clinica-ficticia/appointments", NOTE)

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_request", "fields": ["note"]}
    assert NOTE not in response.text


@pytest.mark.parametrize("nota", ["corta", "x" * 200])
async def test_nota_valida_pasa_sin_error(nota: str) -> None:
    response = await _patch(_app(), PATH, nota)

    assert response.status_code == 200
    assert response.json() == {"note": nota}
