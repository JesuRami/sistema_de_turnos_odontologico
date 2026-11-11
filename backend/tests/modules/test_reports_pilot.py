"""Métricas de éxito del piloto (C-14, D9; KB `01` §Métricas). Postgres y Redis reales.

Los eventos se siembran directo (append-only admite INSERT) con instantes controlados, como los
escribirían los servicios de turnos y de lista de espera. Datos ficticios (regla 13).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from app.core.settings import Settings
from app.models import (
    ActorType,
    Appointment,
    AppointmentEvent,
    AppointmentEventType,
    AppointmentOrigin,
    AppointmentStatus,
    CancellationReason,
    WaitlistEvent,
    WaitlistEventType,
)
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tests.agenda_helpers import Staff, make_staff
from tests.factories import make_appointment, make_patient
from tests.waitlist_helpers import make_entry, make_offer

pytestmark = pytest.mark.integration

URL = "/api/reports/pilot"
ENERO = {"from": "2030-01-01", "to": "2030-01-31"}
BASE = datetime(2030, 1, 15, 13, 0, tzinfo=UTC)


class Escena:
    def __init__(self, db: AsyncSession, staff: Staff) -> None:
        self.db = db
        self.staff = staff
        self.n = 0

    async def turno(self, starts_at: datetime | None = None, **overrides: Any) -> Appointment:
        self.n += 1
        paciente = await make_patient(
            self.db, self.staff.clinic, full_name="Paciente Piloto Ficticio"
        )
        return await make_appointment(
            self.db,
            self.staff.clinic,
            patient=paciente,
            professional=self.staff.professional,
            chair=self.staff.chair,
            starts_at=starts_at or BASE + timedelta(hours=self.n),
            **overrides,
        )

    async def evento(
        self,
        turno: Appointment,
        event: AppointmentEventType,
        to_status: AppointmentStatus | None,
        created_at: datetime,
        **payload: Any,
    ) -> None:
        self.db.add(
            AppointmentEvent(
                clinic_id=turno.clinic_id,
                appointment_id=turno.id,
                actor_type=ActorType.SYSTEM,
                event=event,
                to_status=to_status,
                payload=payload,
                slot_starts_at=turno.starts_at,
                slot_ends_at=turno.ends_at,
                professional_id=turno.professional_id,
                chair_id=turno.chair_id,
                created_at=created_at,
            )
        )
        await self.db.flush()


async def _escena(db: AsyncSession, redis: Redis, settings: Settings) -> Escena:
    return Escena(db, await make_staff(db, redis, settings))


async def _get(client: httpx.AsyncClient, escena: Escena, **params: str) -> dict[str, Any]:
    respuesta = await client.get(
        URL, params={**ENERO, **params}, headers=escena.staff.headers["admin"]
    )
    assert respuesta.status_code == 200, respuesta.text
    return dict(respuesta.json())


async def test_sin_datos_las_metricas_no_tienen_base(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    escena = await _escena(db_session, redis_client, settings)

    cuerpo = await _get(app_client, escena)

    assert (cuerpo["overlaps"], cuerpo["overlaps_ok"]) == (0, True)
    for clave in ("no_show", "confirmation_before_24h", "waitlist_recovery", "online_share"):
        assert cuerpo[clave]["value"] is None
        assert cuerpo[clave]["met"] is None
        assert cuerpo[clave]["denominator"] == 0


async def test_sobreturnos_y_turnos_no_vigentes_no_cuentan_como_solapamiento(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    escena = await _escena(db_session, redis_client, settings)
    await escena.turno(BASE)
    await escena.turno(BASE, is_overbooking=True, overbooking_reason="Urgencia ficticia")
    await escena.turno(BASE, status=AppointmentStatus.ABSENT)

    cuerpo = await _get(app_client, escena)

    assert (cuerpo["overlaps"], cuerpo["overlaps_ok"]) == (0, True)


async def test_proporcion_de_turnos_online(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    escena = await _escena(db_session, redis_client, settings)
    for origen in ("online", "online", "reception"):
        turno = await escena.turno()
        await escena.evento(
            turno,
            AppointmentEventType.CREATED,
            AppointmentStatus.PENDING,
            BASE - timedelta(days=5),
            origin=origen,
        )
    fuera = await escena.turno(BASE + timedelta(days=40))
    await escena.evento(
        fuera, AppointmentEventType.CREATED, AppointmentStatus.PENDING, BASE, origin="online"
    )

    online = (await _get(app_client, escena))["online_share"]

    assert (online["numerator"], online["denominator"]) == (2, 3)
    assert online["value"] == pytest.approx(0.6667)
    assert online["met"] is True


async def test_confirmacion_antes_de_t_menos_24h(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    escena = await _escena(db_session, redis_client, settings)
    pend: dict[str, Any] = {"status": AppointmentStatus.PENDING, "origin": AppointmentOrigin.ONLINE}
    a_tiempo = await escena.turno(**pend)
    tarde = await escena.turno(**pend)
    reserva_de_ultimo_momento = await escena.turno(**pend)
    for turno, creado, confirmado in (
        (a_tiempo, timedelta(days=3), timedelta(days=2)),
        (tarde, timedelta(days=3), timedelta(hours=2)),
        (reserva_de_ultimo_momento, timedelta(hours=10), timedelta(hours=5)),
    ):
        await escena.evento(
            turno,
            AppointmentEventType.CREATED,
            AppointmentStatus.PENDING,
            turno.starts_at - creado,
            origin="online",
        )
        await escena.evento(
            turno,
            AppointmentEventType.CONFIRMED,
            AppointmentStatus.CONFIRMED,
            turno.starts_at - confirmado,
        )

    metrica = (await _get(app_client, escena))["confirmation_before_24h"]

    # La reserva con menos de 24 h de anticipación queda fuera de la base.
    assert (metrica["numerator"], metrica["denominator"]) == (1, 2)
    assert (metrica["value"], metrica["target"], metrica["met"]) == (0.5, 0.6, False)


async def test_huecos_recuperados_por_la_lista_de_espera(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    escena = await _escena(db_session, redis_client, settings)
    clinica = escena.staff.clinic
    for _ in range(2):
        turno = await escena.turno(
            status=AppointmentStatus.CANCELLED,
            cancelled_at=BASE - timedelta(days=1),
            cancellation_reason=CancellationReason.PACIENTE,
        )
        await escena.evento(
            turno,
            AppointmentEventType.CANCELLED,
            AppointmentStatus.CANCELLED,
            BASE - timedelta(days=1),
        )
    paciente = await make_patient(db_session, clinica, full_name="Paciente Espera Ficticio")
    entrada = await make_entry(db_session, clinica, paciente)
    oferta = await make_offer(
        db_session,
        entrada,
        professional=escena.staff.professional,
        chair=escena.staff.chair,
        starts_at=BASE + timedelta(days=2),
    )
    db_session.add(
        WaitlistEvent(
            clinic_id=clinica.id,
            entry_id=entrada.id,
            offer_id=oferta.id,
            event=WaitlistEventType.OFFER_ACCEPTED,
            actor_type=ActorType.SYSTEM,
            payload={},
        )
    )
    await db_session.flush()

    metrica = (await _get(app_client, escena))["waitlist_recovery"]

    assert (metrica["numerator"], metrica["denominator"]) == (1, 2)
    assert metrica["met"] is True


async def test_ausentismo_contra_la_linea_base(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    escena = await _escena(db_session, redis_client, settings)
    for final in (AppointmentStatus.PRESENT, AppointmentStatus.NO_SHOW):
        turno = await escena.turno(status=final)
        await escena.evento(
            turno,
            AppointmentEventType.CREATED,
            AppointmentStatus.CONFIRMED,
            BASE - timedelta(days=3),
        )
        evento = (
            AppointmentEventType.PRESENT
            if final is AppointmentStatus.PRESENT
            else AppointmentEventType.NO_SHOW
        )
        await escena.evento(turno, evento, final, turno.starts_at + timedelta(minutes=40))

    sin_base = (await _get(app_client, escena))["no_show"]
    con_base = (await _get(app_client, escena, baseline_no_show_pct="80"))["no_show"]

    assert (sin_base["value"], sin_base["met"]) == (0.5, None)
    # 50 % actual vs. 80 % de línea base: −37,5 % → cumple la meta de −20 %.
    assert con_base["delta_vs_baseline_pct"] == -37.5
    assert con_base["met"] is True


async def test_csv_solo_admin_y_parametros_cerrados(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    escena = await _escena(db_session, redis_client, settings)
    headers = escena.staff.headers

    csv = await app_client.get(URL, params={**ENERO, "format": "csv"}, headers=headers["admin"])
    recepcion = await app_client.get(URL, params=ENERO, headers=headers["recepcion"])
    desconocido = await app_client.get(
        URL, params={**ENERO, "clinic_id": "otra"}, headers=headers["admin"]
    )
    base_invalida = await app_client.get(
        URL, params={**ENERO, "baseline_no_show_pct": "0"}, headers=headers["admin"]
    )

    assert csv.status_code == 200
    assert csv.text.lstrip("﻿").splitlines()[0] == "metric,value,target,met,numerator,denominator"
    assert "overlaps" in csv.text
    assert recepcion.status_code == 403
    assert desconocido.status_code == 422
    assert base_invalida.status_code == 422
