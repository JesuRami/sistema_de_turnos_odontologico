"""US-004: políticas de clínica — defaults sanos, edición admin, lectura recepción y auditoría."""

from __future__ import annotations

import httpx
import pytest
from app.core.settings import Settings
from app.models import ConfigAction, ConfigEntity
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tests.agenda_helpers import actions, config_events, make_staff

pytestmark = pytest.mark.integration

URL = "/api/clinic/policies"
PASOS_DEFAULT = [
    {"offset_h": 72, "channel": "whatsapp"},
    {"offset_h": 24, "channel": "whatsapp"},
    {"offset_h": 3, "channel": "whatsapp"},
]


@pytest.mark.parametrize("rol", ["admin", "recepcion"])
async def test_clinica_nueva_expone_defaults_sanos(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    rol: str,
) -> None:
    """US-004 CA-1: 24 h, 72/24/3 h, 2 sobreturnos, 4 h de oferta."""
    staff = await make_staff(db_session, redis_client, settings)

    response = await app_client.get(URL, headers=staff.headers[rol])

    assert response.status_code == 200
    assert response.json() == {
        "cancellation_window_hours": 24,
        "reminder_steps": PASOS_DEFAULT,
        "max_overbookings_per_day": 2,
        "waitlist_offer_ttl_hours": 4,
        "contact_phone": None,  # C-08
        "whatsapp_monthly_alert_usd": None,  # C-14
    }


async def test_odontologo_no_accede_a_politicas(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    assert (await app_client.get(URL, headers=staff.headers["odontologo"])).status_code == 403


async def test_admin_cambia_politicas_y_queda_auditado(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    nuevos_pasos = [{"offset_h": 48, "channel": "whatsapp"}, {"offset_h": 2, "channel": "email"}]

    response = await app_client.patch(
        URL,
        json={"cancellation_window_hours": 48, "reminder_steps": nuevos_pasos},
        headers=staff.headers["admin"],
    )

    assert response.status_code == 200
    assert response.json()["cancellation_window_hours"] == 48
    assert response.json()["reminder_steps"] == nuevos_pasos
    assert response.json()["max_overbookings_per_day"] == 2
    await db_session.refresh(staff.clinic)
    assert staff.clinic.cancellation_window_hours == 48
    eventos = await config_events(db_session, ConfigEntity.CLINIC_POLICY, staff.clinic.id)
    assert actions(eventos) == [ConfigAction.UPDATED]
    assert eventos[0].changes == {
        "cancellation_window_hours": [24, 48],
        "reminder_steps": [PASOS_DEFAULT, nuevos_pasos],
    }


async def test_patch_sin_cambios_no_audita(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)

    response = await app_client.patch(
        URL, json={"max_overbookings_per_day": 2}, headers=staff.headers["admin"]
    )

    assert response.status_code == 200
    assert await config_events(db_session, ConfigEntity.CLINIC_POLICY, staff.clinic.id) == []


@pytest.mark.parametrize(
    "invalido",
    [
        {"cancellation_window_hours": -1},
        {"max_overbookings_per_day": -1},
        {"waitlist_offer_ttl_hours": 0},
        {"reminder_steps": []},
        {"reminder_steps": [{"offset_h": 24, "channel": "whatsapp"}] * 2},
        {"reminder_steps": [{"offset_h": 24, "channel": "sms"}]},
        {"reminder_steps": [{"offset_h": h, "channel": "email"} for h in range(1, 7)]},
        {"cancellation_window_hours": None},
        {"clinic_id": "00000000-0000-0000-0000-000000000000"},
    ],
)
async def test_politica_invalida_es_422_y_no_cambia(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    invalido: dict[str, object],
) -> None:
    staff = await make_staff(db_session, redis_client, settings)

    response = await app_client.patch(URL, json=invalido, headers=staff.headers["admin"])

    assert response.status_code == 422
    assert (await app_client.get(URL, headers=staff.headers["admin"])).json()[
        "reminder_steps"
    ] == PASOS_DEFAULT


async def test_recepcion_no_edita_politicas(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    response = await app_client.patch(
        URL, json={"cancellation_window_hours": 1}, headers=staff.headers["recepcion"]
    )
    assert response.status_code == 403


async def test_cada_clinica_edita_solo_sus_politicas(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    otra = await make_staff(db_session, redis_client, settings)

    await app_client.patch(
        URL, json={"waitlist_offer_ttl_hours": 12}, headers=otra.headers["admin"]
    )

    propia = await app_client.get(URL, headers=staff.headers["admin"])
    assert propia.json()["waitlist_offer_ttl_hours"] == 4
    await db_session.refresh(otra.clinic)
    assert otra.clinic.waitlist_offer_ttl_hours == 12
