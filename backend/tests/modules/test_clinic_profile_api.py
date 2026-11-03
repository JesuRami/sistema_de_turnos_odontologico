"""`GET /api/clinic`: perfil de la clínica para todo el personal (C-06 tarea 2.1, D10)."""

from __future__ import annotations

import httpx
import pytest
from app.core.settings import Settings
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tests.agenda_helpers import make_staff

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("rol", ["admin", "recepcion", "odontologo"])
async def test_el_personal_ve_nombre_y_zona_de_su_clinica(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    rol: str,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    otra = await make_staff(db_session, redis_client, settings)

    response = await app_client.get("/api/clinic", headers=staff.headers[rol])

    assert response.status_code == 200, response.text
    assert response.json() == {
        "id": str(staff.clinic.id),
        "name": staff.clinic.name,
        "timezone": "America/Argentina/Buenos_Aires",
    }
    assert str(otra.clinic.id) not in response.text


async def test_sin_token_es_401(app_client: httpx.AsyncClient) -> None:
    response = await app_client.get("/api/clinic")
    assert response.status_code == 401
