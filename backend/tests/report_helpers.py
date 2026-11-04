"""Helpers de los tests de reportes (C-13): altas y transiciones por la API real.

Todo pasa por los endpoints de turnos para que los eventos (y su instantánea)
los escriba la aplicación, igual que en producción. Datos ficticios (regla 13).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import httpx

from tests.appointment_helpers import Agenda, at, post

# Lunes 2030-01-14 (la regla sintética es de lunes) y el lunes siguiente.
DIA = date(2030, 1, 14)
DIA2 = date(2030, 1, 21)


def rango(desde: date = DIA, hasta: date = DIA, **extra: str) -> dict[str, str]:
    return {"from": desde.isoformat(), "to": hasta.isoformat(), **extra}


async def alta(
    client: httpx.AsyncClient,
    agenda: Agenda,
    hh: int,
    mm: int = 0,
    *,
    days: int = 7,
    duration: int = 30,
    rol: str = "recepcion",
    **extra: Any,
) -> str:
    """Crea un turno confirmado por la API y devuelve su id."""
    response = await post(
        client, agenda, at(hh, mm, days=days), rol, duration_min=duration, **extra
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def transicion(
    client: httpx.AsyncClient,
    agenda: Agenda,
    appointment_id: str,
    destino: str,
    rol: str = "recepcion",
    **extra: Any,
) -> None:
    response = await client.post(
        f"/api/appointments/{appointment_id}/transitions",
        json={"to": destino, **extra},
        headers=agenda.headers[rol],
    )
    assert response.status_code == 200, response.text


async def reporte(
    client: httpx.AsyncClient,
    agenda: Agenda,
    nombre: str,
    rol: str = "admin",
    **params: str,
) -> httpx.Response:
    return await client.get(
        f"/api/reports/{nombre}", params=rango(**{}) | params, headers=agenda.headers[rol]
    )


def fijar_reloj(reloj: Any, instante: datetime) -> None:
    reloj.current = instante
