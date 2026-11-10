"""Anotación pública en la lista de espera (C-12, D7; spec waitlist/entries).

`POST /api/booking/{slug}/waiting-list`: sin sesión, mismos contactos y consentimientos que la
reserva online, cupos propios por IP y por slug, `BotGuard` y 404 uniforme. Postgres y Redis
reales; reloj de la app en `AGENDA_NOW` (lunes 07/01/2030). Datos ficticios (regla 13).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
import pytest
from app.core.redis import get_redis
from app.core.settings import Settings, get_settings
from app.models import (
    Consent,
    ConsentSource,
    Patient,
    WaitingListEntry,
    WaitlistEvent,
)
from app.modules.booking_public.guard import BotGuard, get_bot_guard
from fastapi import FastAPI, Request
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.booking_helpers import (
    EMAIL,
    NOMBRE,
    TELEFONO_E164,
    TELEFONO_NACIONAL,
    PublicBooking,
    make_booking,
)
from tests.conftest import MutableClock
from tests.factories import make_clinic, make_patient

pytestmark = pytest.mark.integration


def _url(slug: str) -> str:
    return f"/api/booking/{slug}/waiting-list"


def _cuerpo(b: PublicBooking | None = None, **cambios: Any) -> dict[str, Any]:
    paciente: dict[str, Any] = {
        "full_name": NOMBRE,
        "phone": TELEFONO_NACIONAL,
        "whatsapp_opt_in": True,
        "privacy_accepted": True,
    }
    paciente.update(cambios.pop("patient", {}))
    cuerpo: dict[str, Any] = {
        "professional_id": str(b.professional.id) if b else None,
        "date_from": "2030-01-08",
        "date_to": "2030-01-20",
        "patient": paciente,
    }
    cuerpo.update(cambios)
    return cuerpo


async def _entradas(db: AsyncSession, clinic_id: object) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(WaitingListEntry)
            .where(WaitingListEntry.clinic_id == clinic_id)
        )
        or 0
    )


def _con_settings(app: FastAPI, settings: Settings, **cambios: object) -> None:
    app.dependency_overrides[get_settings] = lambda: settings.model_copy(update=cambios)


async def test_anotacion_publica_exitosa(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)

    r = await app_client.post(
        _url(b.slug), json=_cuerpo(b, time_from="09:00", time_to="12:00", weekdays=[0, 2])
    )

    assert r.status_code == 201, r.text
    cuerpo = r.json()
    assert cuerpo["professional_id"] == str(b.professional.id)
    assert cuerpo["date_from"] == "2030-01-08"
    assert cuerpo["weekdays"] == [0, 2]
    assert cuerpo["channel"] == "whatsapp"
    assert "id" not in cuerpo and "patient_id" not in cuerpo
    assert r.headers["cache-control"] == "no-store"
    entrada = await db_session.scalar(
        select(WaitingListEntry).where(WaitingListEntry.clinic_id == b.clinic.id)
    )
    assert entrada is not None
    assert entrada.source == "online"
    assert entrada.status.value == "waiting"
    evento = await db_session.scalar(
        select(WaitlistEvent).where(WaitlistEvent.entry_id == entrada.id)
    )
    assert evento is not None and evento.actor_type.value == "patient_token"


async def test_cualquiera_sin_profesional(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)

    r = await app_client.post(_url(b.slug), json=_cuerpo())

    assert r.status_code == 201, r.text
    assert r.json()["professional_id"] is None


@pytest.mark.parametrize(
    ("cambios", "detalle"),
    [
        ({"patient": {"phone": None}}, "contact_required"),
        ({"patient": {"privacy_accepted": False}}, "privacy_consent_required"),
        ({"patient": {"whatsapp_opt_in": None}}, "whatsapp_opt_in_required"),
        ({"date_from": "2030-01-20", "date_to": "2030-01-10"}, "invalid_range"),
        ({"time_from": "12:00"}, "invalid_time_window"),
    ],
)
async def test_validaciones(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    agenda_clock: MutableClock,
    cambios: dict[str, Any],
    detalle: str,
) -> None:
    b = await make_booking(db_session)

    r = await app_client.post(_url(b.slug), json=_cuerpo(b, **cambios))

    assert r.status_code == 422, r.text
    assert r.json()["detail"] == detalle
    assert await _entradas(db_session, b.clinic.id) == 0
    pacientes = await db_session.scalar(
        select(func.count()).select_from(Patient).where(Patient.clinic_id == b.clinic.id)
    )
    assert pacientes == 0


async def test_campo_desconocido(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)

    r = await app_client.post(_url(b.slug), json=_cuerpo(b, notes="hola"))

    assert r.status_code == 422


async def test_paciente_existente_reutilizado_y_opt_in(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)
    existente = await make_patient(
        db_session, b.clinic, full_name=NOMBRE, phone_e164=TELEFONO_E164, whatsapp_opt_in=False
    )

    r = await app_client.post(_url(b.slug), json=_cuerpo(b))

    assert r.status_code == 201, r.text
    entrada = await db_session.scalar(
        select(WaitingListEntry).where(WaitingListEntry.clinic_id == b.clinic.id)
    )
    assert entrada is not None and entrada.patient_id == existente.id
    pacientes = await db_session.scalar(
        select(func.count()).select_from(Patient).where(Patient.clinic_id == b.clinic.id)
    )
    assert pacientes == 1
    consentimiento = await db_session.scalar(
        select(Consent).where(Consent.patient_id == existente.id)
    )
    assert consentimiento is not None and consentimiento.source is ConsentSource.BOOKING


async def test_solo_email(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)

    r = await app_client.post(
        _url(b.slug), json=_cuerpo(b, patient={"phone": None, "email": EMAIL})
    )

    assert r.status_code == 201, r.text
    assert r.json()["channel"] == "email"


async def test_duplicado_sin_datos_del_paciente(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)
    b.clinic.contact_phone = "+5491155550100"
    await app_client.post(_url(b.slug), json=_cuerpo(b))

    r = await app_client.post(_url(b.slug), json=_cuerpo(b))

    assert r.status_code == 409, r.text
    # Sin datos del paciente; solo el teléfono público de la clínica.
    assert r.json() == {"detail": "already_waiting", "clinic_phone": "+5491155550100"}
    assert await _entradas(db_session, b.clinic.id) == 1


async def test_slug_inexistente_y_deshabilitado(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    cerrada = await make_clinic(db_session, booking_enabled=False)

    for slug in ("no-existe-ficticia", cerrada.slug):
        r = await app_client.post(_url(slug), json=_cuerpo())
        assert r.status_code == 404
        assert r.json() == {"detail": "booking_not_found"}


async def test_profesional_no_reservable(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)
    otra = await make_booking(db_session)

    r = await app_client.post(_url(b.slug), json=_cuerpo(otra))

    assert r.status_code == 404
    assert r.json() == {"detail": "professional_not_found"}


async def test_cupo_por_ip(
    app_instance: FastAPI,
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    _con_settings(app_instance, settings, WAITLIST_PUBLIC_IP_RATE_LIMIT="1/3600s")
    b = await make_booking(db_session)

    primera = await app_client.post(_url(b.slug), json=_cuerpo(b))
    segunda = await app_client.post(
        _url(b.slug), json=_cuerpo(patient={"phone": "011 15 5555-0199"})
    )

    assert primera.status_code == 201, primera.text
    assert segunda.status_code == 429
    assert segunda.json()["detail"] == "rate_limited"
    assert int(segunda.headers["retry-after"]) > 0
    assert await _entradas(db_session, b.clinic.id) == 1


async def test_cupo_por_slug(
    app_instance: FastAPI,
    client_factory: Any,
    db_session: AsyncSession,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    _con_settings(app_instance, settings, WAITLIST_PUBLIC_SLUG_RATE_LIMIT="1/3600s")
    b = await make_booking(db_session)
    async with client_factory("198.51.100.10") as una, client_factory("198.51.100.11") as otra:
        assert (await una.post(_url(b.slug), json=_cuerpo(b))).status_code == 201
        r = await otra.post(_url(b.slug), json=_cuerpo(patient={"phone": "011 15 5555-0198"}))

    assert r.status_code == 429


async def test_redis_caido_da_503(
    app_instance: FastAPI,
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    agenda_clock: MutableClock,
) -> None:
    b = await make_booking(db_session)
    caido: Redis = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.5)

    async def _override() -> Redis:
        return caido

    app_instance.dependency_overrides[get_redis] = _override
    try:
        r = await app_client.post(_url(b.slug), json=_cuerpo(b))
    finally:
        await caido.aclose()

    assert r.status_code == 503
    assert r.json() == {"detail": "booking_unavailable"}
    assert await _entradas(db_session, b.clinic.id) == 0


class _GuardQueRechaza:
    async def verify(self, request: Request, *, action: str) -> None:
        from app.common.exceptions import DomainError

        raise DomainError(403, "bot_check_failed")


async def test_bot_guard_invocado(
    app_instance: FastAPI,
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    agenda_clock: MutableClock,
) -> None:
    b = await make_booking(db_session)
    rechazo: BotGuard = _GuardQueRechaza()
    app_instance.dependency_overrides[get_bot_guard] = lambda: rechazo

    r = await app_client.post(_url(b.slug), json=_cuerpo(b))

    assert r.status_code == 403
    assert await _entradas(db_session, b.clinic.id) == 0


async def test_sin_pii_en_logs(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    agenda_clock: MutableClock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    b = await make_booking(db_session)
    caplog.set_level(logging.DEBUG)

    await app_client.post(_url(b.slug), json=_cuerpo(b))
    await app_client.post(_url(b.slug), json=_cuerpo(b))

    texto = caplog.text
    for dato in (NOMBRE, TELEFONO_E164, "5555-0123"):
        assert dato not in texto
