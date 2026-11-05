"""Teléfono de contacto de la clínica en las políticas (C-08, D12): E.164, solo admin."""

from __future__ import annotations

import httpx
import pytest
from app.core.settings import Settings
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tests.agenda_helpers import make_staff

pytestmark = pytest.mark.integration

URL = "/api/clinic/policies"


async def test_admin_guarda_el_telefono_normalizado(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)

    response = await app_client.patch(
        URL, json={"contact_phone": "+54 11 5555-0100"}, headers=staff.headers["admin"]
    )

    assert response.status_code == 200, response.text
    assert response.json()["contact_phone"] == "+541155550100"
    leido = await app_client.get(URL, headers=staff.headers["recepcion"])
    assert leido.json()["contact_phone"] == "+541155550100"


async def test_clinica_nueva_sin_telefono(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    response = await app_client.get(URL, headers=staff.headers["admin"])
    assert response.json()["contact_phone"] is None


async def test_recepcion_no_cambia_el_telefono(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)

    response = await app_client.patch(
        URL, json={"contact_phone": "+54 11 5555-0100"}, headers=staff.headers["recepcion"]
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "forbidden_role"}


@pytest.mark.parametrize("valor", ["123", "telefono", None], ids=["corto", "texto", "null"])
async def test_telefono_invalido_o_null_es_422_y_conserva_el_anterior(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    valor: str | None,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    await app_client.patch(
        URL, json={"contact_phone": "+54 11 5555-0100"}, headers=staff.headers["admin"]
    )

    response = await app_client.patch(
        URL, json={"contact_phone": valor}, headers=staff.headers["admin"]
    )

    assert response.status_code == 422
    assert valor is None or valor not in response.text
    leido = await app_client.get(URL, headers=staff.headers["admin"])
    assert leido.json()["contact_phone"] == "+541155550100"
