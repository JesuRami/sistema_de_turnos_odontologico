"""Link público de la oferta `/api/waitlist-offer/{token}` (C-12, D6; spec waitlist/offer-link).

Postgres y Redis reales; reloj de la app en `AGENDA_NOW` (lunes 07/01/2030 08:00 local); secreto
de links conocido. Datos ficticios (regla 13).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, time, timedelta
from typing import Any

import httpx
import pytest
from app.core.redis import get_redis
from app.core.settings import Settings, get_settings
from app.models import (
    Appointment,
    AppointmentOrigin,
    Patient,
    WaitingListEntry,
    WaitingListStatus,
    WaitlistEvent,
    WaitlistOffer,
    WaitlistOfferStatus,
)
from app.modules.reminders.links import sign_manage_token
from app.modules.waiting_list.links import sign_offer_token
from fastapi import FastAPI
from pydantic import SecretStr
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.agenda_helpers import Staff, make_staff
from tests.conftest import AGENDA_NOW, MutableClock
from tests.factories import make_appointment, make_patient, make_schedule_rule
from tests.waitlist_helpers import make_entry, make_offer

pytestmark = pytest.mark.integration

SECRETO = "firma-de-links-solo-para-tests-32-bytes-ok"
HUECO = AGENDA_NOW + timedelta(days=2, hours=2)  # miércoles 10:00 local
NOMBRE = "Valentina Espera Ficticia"
TELEFONO = "+5491155550177"
URL = "/api/waitlist-offer"


@pytest.fixture()
def firma(app_instance: FastAPI, settings: Settings) -> Settings:
    con_secreto = settings.model_copy(update={"MANAGE_LINK_SECRET": SecretStr(SECRETO)})
    app_instance.dependency_overrides[get_settings] = lambda: con_secreto
    return con_secreto


@dataclass
class Escena:
    staff: Staff
    paciente: Patient
    entry: WaitingListEntry
    offer: WaitlistOffer

    @property
    def token(self) -> str:
        return sign_offer_token(SECRETO, self.offer.id)


async def _escena(db: AsyncSession, redis: Redis, settings: Settings, **oferta: Any) -> Escena:
    staff = await make_staff(db, redis, settings)
    staff.clinic.contact_phone = "+5491155550100"
    await make_schedule_rule(
        db,
        staff.clinic,
        staff.professional,
        staff.chair,
        weekday=2,
        start_time=time(9),
        end_time=time(13),
    )
    paciente = await make_patient(
        db, staff.clinic, full_name=NOMBRE, phone_e164=TELEFONO, whatsapp_opt_in=True
    )
    entry = await make_entry(
        db,
        staff.clinic,
        paciente,
        status=WaitingListStatus.OFFERED,
        date_from=date(2030, 1, 7),
        date_to=date(2030, 1, 20),
    )
    valores: dict[str, Any] = {"now": AGENDA_NOW}
    valores.update(oferta)
    offer = await make_offer(
        db,
        entry,
        professional=staff.professional,
        chair=staff.chair,
        starts_at=valores.pop("starts_at", HUECO),
        **valores,
    )
    return Escena(staff, paciente, entry, offer)


def _sin_pii(texto: str) -> None:
    for dato in (NOMBRE.split()[1], TELEFONO, "5555-0177"):
        assert dato not in texto


async def test_vista_de_oferta_pendiente(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    firma: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, firma)

    r = await app_client.get(f"{URL}/{e.token}")

    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["status"] == "pending"
    assert cuerpo["patient_first_name"] == "Valentina"
    assert cuerpo["clinic_phone"] == "+5491155550100"
    assert cuerpo["starts_at"] == "2030-01-09T13:00:00Z"
    assert cuerpo["expires_at"] == "2030-01-07T15:00:00Z"
    assert cuerpo["appointment"] is None
    assert "patient_id" not in cuerpo and "id" not in cuerpo
    _sin_pii(r.text)
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["referrer-policy"] == "no-referrer"


async def test_vista_de_oferta_vencida_antes_del_tick(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    firma: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, firma, expires_in=timedelta(minutes=-1))

    r = await app_client.get(f"{URL}/{e.token}")

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "expired"


async def test_aceptar_por_link_y_ver_aceptada(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    firma: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, firma)

    r = await app_client.post(f"{URL}/{e.token}/accept")

    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["status"] == "accepted"
    assert cuerpo["appointment"]["starts_at"] == "2030-01-09T13:00:00Z"
    turno = await db_session.scalar(
        select(Appointment).where(Appointment.patient_id == e.paciente.id)
    )
    assert turno is not None and turno.origin is AppointmentOrigin.WAITLIST
    assert cuerpo["appointment"]["manage_url"].endswith(
        "/g/" + sign_manage_token(SECRETO, turno.id)
    )
    vista = await app_client.get(f"{URL}/{e.token}")
    assert vista.json()["status"] == "accepted"
    assert vista.json()["appointment"]["starts_at"] == "2030-01-09T13:00:00Z"


@pytest.mark.parametrize("salir", [False, True])
async def test_rechazar_por_link(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    firma: Settings,
    agenda_clock: MutableClock,
    salir: bool,
) -> None:
    e = await _escena(db_session, redis_client, firma)

    r = await app_client.post(
        f"{URL}/{e.token}/decline", json={"leave_list": True} if salir else None
    )

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "declined"
    await db_session.refresh(e.entry)
    esperado = WaitingListStatus.WITHDRAWN if salir else WaitingListStatus.WAITING
    assert e.entry.status is esperado


async def test_campo_desconocido_en_el_rechazo(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    firma: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, firma)

    r = await app_client.post(f"{URL}/{e.token}/decline", json={"motivo": "x"})

    assert r.status_code == 422
    await db_session.refresh(e.offer)
    assert e.offer.status is WaitlistOfferStatus.PENDING


async def test_credenciales_invalidas_responden_igual(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    firma: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, firma)
    alterado = e.token[:-2] + ("A" if e.token[-2] != "A" else "B") + e.token[-1]
    turno = await make_appointment(
        db_session,
        e.staff.clinic,
        patient=e.paciente,
        professional=e.staff.professional,
        chair=e.staff.chair,
        starts_at=HUECO + timedelta(days=7),
    )

    cuerpos = []
    for token in (
        alterado,
        sign_manage_token(SECRETO, turno.id),
        sign_offer_token(SECRETO, uuid.uuid4()),
        "basura",
    ):
        r = await app_client.get(f"{URL}/{token}")
        assert r.status_code == 404, token
        cuerpos.append(r.json())
    assert all(c == {"detail": "offer_not_found"} for c in cuerpos)


async def test_link_viejo(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    firma: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, firma)
    agenda_clock.current = HUECO + timedelta(days=4)

    r = await app_client.get(f"{URL}/{e.token}")

    assert r.status_code == 404
    assert r.json() == {"detail": "offer_not_found"}


async def test_hueco_ocupado_informa_alternativos(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    firma: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, firma)
    titular = await make_patient(db_session, e.staff.clinic)
    await make_appointment(
        db_session,
        e.staff.clinic,
        patient=titular,
        professional=e.staff.professional,
        chair=e.staff.chair,
        starts_at=HUECO,
    )

    r = await app_client.post(f"{URL}/{e.token}/accept")

    assert r.status_code == 409
    assert r.json()["detail"] == "slot_taken"
    assert all(set(a) == {"starts_at", "ends_at"} for a in r.json()["alternatives"])


async def test_cupo_por_token_y_por_ip(
    app_instance: FastAPI,
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    firma: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, firma)
    limitado = firma.model_copy(update={"MANAGE_WRITE_TOKEN_RATE_LIMIT": "1/60s"})
    app_instance.dependency_overrides[get_settings] = lambda: limitado

    primera = await app_client.post(f"{URL}/{e.token}/decline", json={"motivo": "x"})
    segunda = await app_client.post(f"{URL}/{e.token}/accept")

    assert primera.status_code == 422
    assert segunda.status_code == 429
    assert int(segunda.headers["retry-after"]) > 0
    await db_session.refresh(e.offer)
    assert e.offer.status is WaitlistOfferStatus.PENDING


async def test_redis_caido(
    app_instance: FastAPI,
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    firma: Settings,
    agenda_clock: MutableClock,
) -> None:
    e = await _escena(db_session, redis_client, firma)
    caido: Redis = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.5)

    async def _override() -> Redis:
        return caido

    app_instance.dependency_overrides[get_redis] = _override
    try:
        r = await app_client.get(f"{URL}/{e.token}")
    finally:
        await caido.aclose()

    assert r.status_code == 503


async def test_el_token_no_queda_en_logs_ni_eventos(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    firma: Settings,
    agenda_clock: MutableClock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    e = await _escena(db_session, redis_client, firma)
    caplog.set_level(logging.DEBUG)

    await app_client.get(f"{URL}/{e.token}")
    await app_client.post(f"{URL}/{e.token}/accept")

    # Solo logs de la app: `httpx`/`httpcore` son el cliente de test pidiendo la URL.
    de_la_app = " | ".join(
        r.getMessage() for r in caplog.records if not r.name.startswith(("httpx", "httpcore"))
    )
    assert e.token not in de_la_app
    _sin_pii(de_la_app)
    eventos = (
        await db_session.execute(
            select(WaitlistEvent.payload).where(WaitlistEvent.offer_id == e.offer.id)
        )
    ).scalars()
    assert all(e.token not in str(p) for p in eventos)
