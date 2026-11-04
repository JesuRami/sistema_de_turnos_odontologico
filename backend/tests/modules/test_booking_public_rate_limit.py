"""Anti-abuso de la reserva pública (C-07, D2): cupos Redis por IP/slug, fail-closed y BotGuard."""

from __future__ import annotations

from collections.abc import Callable
from datetime import time

import httpx
import pytest
from app.core.redis import get_redis
from app.core.settings import Settings, get_settings
from app.models import Appointment, Patient
from app.modules.booking_public.guard import BotGuard, get_bot_guard
from fastapi import FastAPI, Request
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.appointment_helpers import at, iso
from tests.booking_helpers import PublicBooking, make_booking, reserva
from tests.conftest import MutableClock
from tests.factories import make_clinic

pytestmark = pytest.mark.integration


def _url(b: PublicBooking) -> str:
    return f"/api/booking/{b.slug}/appointments"


def _con_settings(app: FastAPI, settings: Settings, **cambios: object) -> None:
    app.dependency_overrides[get_settings] = lambda: settings.model_copy(update=cambios)


async def _conteos(db_session: AsyncSession, b: PublicBooking) -> tuple[int, int]:
    pacientes = await db_session.scalar(
        select(func.count()).select_from(Patient).where(Patient.clinic_id == b.clinic.id)
    )
    turnos = await db_session.scalar(
        select(func.count()).select_from(Appointment).where(Appointment.clinic_id == b.clinic.id)
    )
    return int(pacientes or 0), int(turnos or 0)


def _telefono(n: int) -> str:
    return f"011 15 5555-{n:04d}"


# ------------------------------------------------------------ lecturas (3.5)


async def test_superar_el_cupo_de_lecturas_da_429_con_retry_after(
    app_instance: FastAPI,
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    b = await make_booking(db_session)
    _con_settings(app_instance, settings, PUBLIC_BOOKING_READ_RATE_LIMIT="3/60s")

    estados = [(await app_client.get(f"/api/booking/{b.slug}")).status_code for _ in range(3)]
    cuarta = await app_client.get(f"/api/booking/{b.slug}")

    assert estados == [200, 200, 200]
    assert cuarta.status_code == 429
    assert cuarta.json() == {"detail": "rate_limited"}
    assert 0 < int(cuarta.headers["Retry-After"]) <= 60


async def test_el_cupo_de_lecturas_cuenta_tambien_la_disponibilidad(
    app_instance: FastAPI,
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    b = await make_booking(db_session)
    _con_settings(app_instance, settings, PUBLIC_BOOKING_READ_RATE_LIMIT="2/60s")
    params = {
        "professional_id": str(b.professional.id),
        "from": at(0).isoformat(),
        "to": at(0, days=1).isoformat(),
    }

    primera = await app_client.get(f"/api/booking/{b.slug}/availability", params=params)
    segunda = await app_client.get(f"/api/booking/{b.slug}")
    tercera = await app_client.get(f"/api/booking/{b.slug}/availability", params=params)

    assert (primera.status_code, segunda.status_code) == (200, 200)
    assert tercera.status_code == 429


async def test_barrer_slugs_inexistentes_da_429_en_lugar_de_404(
    app_instance: FastAPI,
    app_client: httpx.AsyncClient,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    _con_settings(app_instance, settings, PUBLIC_BOOKING_READ_RATE_LIMIT="2/60s")

    estados = [(await app_client.get(f"/api/booking/no-existe-{n}")).status_code for n in range(3)]

    assert estados == [404, 404, 429]


async def test_otra_ip_no_comparte_el_cupo_de_lecturas(
    app_instance: FastAPI,
    client_factory: Callable[..., httpx.AsyncClient],
    db_session: AsyncSession,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    b = await make_booking(db_session)
    _con_settings(app_instance, settings, PUBLIC_BOOKING_READ_RATE_LIMIT="1/60s")
    async with client_factory("198.51.100.1") as una, client_factory("198.51.100.2") as otra:
        assert (await una.get(f"/api/booking/{b.slug}")).status_code == 200
        assert (await una.get(f"/api/booking/{b.slug}")).status_code == 429

        assert (await otra.get(f"/api/booking/{b.slug}")).status_code == 200


async def _redis_caido(app: FastAPI) -> Redis:
    caido: Redis = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.5)

    async def _override() -> Redis:
        return caido

    app.dependency_overrides[get_redis] = _override
    return caido


async def test_redis_caido_da_503_booking_unavailable_en_lecturas(
    app_instance: FastAPI,
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    agenda_clock: MutableClock,
) -> None:
    b = await make_booking(db_session)
    caido = await _redis_caido(app_instance)
    try:
        catalogo = await app_client.get(f"/api/booking/{b.slug}")
        disponibilidad = await app_client.get(
            f"/api/booking/{b.slug}/availability",
            params={
                "professional_id": str(b.professional.id),
                "from": at(0).isoformat(),
                "to": at(0, days=1).isoformat(),
            },
        )
    finally:
        await caido.aclose()

    for response in (catalogo, disponibilidad):
        assert response.status_code == 503
        assert response.json() == {"detail": "booking_unavailable"}
        assert "slots" not in response.text


# ------------------------------------------------------------ reservas (9.1)


async def test_la_undecima_reserva_de_la_misma_ip_da_429_sin_crear_turno(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session, end_time=time(17))
    horarios = [iso(9 + n // 2, 30 * (n % 2)) for n in range(11)]

    estados = []
    for n, inicio in enumerate(horarios):
        response = await app_client.post(
            _url(b), json=reserva(b, inicio, full_name=f"Paciente Cupo {n}", phone=_telefono(n))
        )
        estados.append(response.status_code)

    assert estados == [201] * 10 + [429]
    assert response.json() == {"detail": "rate_limited"}
    assert int(response.headers["Retry-After"]) > 0
    assert (await _conteos(db_session, b))[1] == 10


async def test_un_422_tambien_consume_cupo(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)
    invalida = reserva(b, iso(10), phone=None, whatsapp_opt_in=None)

    invalidas = [(await app_client.post(_url(b), json=invalida)).status_code for _ in range(10)]
    valida = await app_client.post(_url(b), json=reserva(b, iso(10)))

    assert invalidas == [422] * 10
    assert valida.status_code == 429
    assert await _conteos(db_session, b) == (0, 0)


async def test_otra_ip_sigue_pudiendo_reservar(
    client_factory: Callable[..., httpx.AsyncClient],
    db_session: AsyncSession,
    agenda_clock: MutableClock,
) -> None:
    b = await make_booking(db_session)
    async with client_factory("198.51.100.10") as agotada, client_factory("198.51.100.11") as otra:
        for _ in range(10):
            await agotada.post(_url(b), json=reserva(b, iso(10), phone=None, whatsapp_opt_in=None))
        assert (await agotada.post(_url(b), json=reserva(b, iso(10)))).status_code == 429

        respuesta = await otra.post(_url(b), json=reserva(b, iso(10)))

    assert respuesta.status_code == 201, respuesta.text


async def test_cupo_por_slug_agotado_da_429_para_cualquier_ip(
    app_instance: FastAPI,
    client_factory: Callable[..., httpx.AsyncClient],
    db_session: AsyncSession,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    b = await make_booking(db_session)
    _con_settings(app_instance, settings, PUBLIC_BOOKING_SLUG_RATE_LIMIT="2/3600s")
    cuerpos = [
        reserva(b, iso(9), full_name="Paciente Slug Uno", phone=_telefono(1)),
        reserva(b, iso(9, 30), full_name="Paciente Slug Dos", phone=_telefono(2)),
        reserva(b, iso(10), full_name="Paciente Slug Tres", phone=_telefono(3)),
    ]

    estados = []
    for n, cuerpo in enumerate(cuerpos):
        async with client_factory(f"198.51.100.{20 + n}") as client:
            estados.append((await client.post(_url(b), json=cuerpo)).status_code)

    assert estados == [201, 201, 429]
    assert (await _conteos(db_session, b))[1] == 2


async def test_el_cupo_por_slug_no_se_consume_con_slug_inexistente(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    agenda_clock: MutableClock,
) -> None:
    b = await make_booking(db_session)

    respuesta = await app_client.post(
        "/api/booking/no-existe-xyz/appointments", json=reserva(b, iso(10))
    )

    assert respuesta.status_code == 404
    claves = [c async for c in redis_client.scan_iter("rl:booking:create:slug:*")]
    assert claves == []


async def test_el_cupo_por_slug_de_una_clinica_no_afecta_a_otra(
    app_instance: FastAPI,
    client_factory: Callable[..., httpx.AsyncClient],
    db_session: AsyncSession,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    a = await make_booking(db_session)
    otra = await make_booking(
        db_session, clinic=await make_clinic(db_session, booking_enabled=True)
    )
    _con_settings(app_instance, settings, PUBLIC_BOOKING_SLUG_RATE_LIMIT="1/3600s")
    async with client_factory("198.51.100.30") as uno, client_factory("198.51.100.31") as dos:
        assert (await uno.post(_url(a), json=reserva(a, iso(10)))).status_code == 201
        assert (await dos.post(_url(a), json=reserva(a, iso(11)))).status_code == 429

        respuesta = await dos.post(_url(otra), json=reserva(otra, iso(10)))

    assert respuesta.status_code == 201, respuesta.text


async def test_redis_caido_da_503_en_reservas_y_no_crea_turno(
    app_instance: FastAPI,
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    agenda_clock: MutableClock,
) -> None:
    b = await make_booking(db_session)
    caido = await _redis_caido(app_instance)
    try:
        response = await app_client.post(_url(b), json=reserva(b, iso(10)))
    finally:
        await caido.aclose()

    assert response.status_code == 503
    assert response.json() == {"detail": "booking_unavailable"}
    assert await _conteos(db_session, b) == (0, 0)


# ------------------------------------------------------------ BotGuard (9.3)


class _GuardQueRechaza:
    async def verify(self, request: Request, *, action: str) -> None:
        from app.common.exceptions import DomainError

        raise DomainError(403, "bot_check_failed")


async def test_sin_campo_de_captcha_el_guard_noop_deja_pasar(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)

    response = await app_client.post(_url(b), json=reserva(b, iso(10)))

    assert response.status_code == 201, response.text


async def test_un_guard_que_rechaza_da_403_y_no_crea_nada(
    app_instance: FastAPI,
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    agenda_clock: MutableClock,
) -> None:
    b = await make_booking(db_session)
    rechazo: BotGuard = _GuardQueRechaza()
    app_instance.dependency_overrides[get_bot_guard] = lambda: rechazo

    response = await app_client.post(_url(b), json=reserva(b, iso(10)))

    assert response.status_code == 403
    assert response.json() == {"detail": "bot_check_failed"}
    assert await _conteos(db_session, b) == (0, 0)
