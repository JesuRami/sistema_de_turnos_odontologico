"""Volumen sintético: los reportes y el export responden con muchos turnos (C-13, S6)."""

from __future__ import annotations

import io
import time
import zipfile
from datetime import timedelta

import httpx
import pytest
from app.core.settings import Settings
from app.models import ActorType, AppointmentEvent, AppointmentEventType, AppointmentStatus
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tests.appointment_helpers import at, make_agenda
from tests.conftest import MutableClock
from tests.factories import make_appointment
from tests.report_helpers import DIA, rango

pytestmark = pytest.mark.integration

VOLUMEN = 1000


async def test_reportes_y_export_con_mil_turnos(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    base = at(0, 0, days=7)
    for i in range(VOLUMEN):
        inicio = base + timedelta(minutes=30 * i)
        turno = await make_appointment(
            db_session,
            agenda.staff.clinic,
            patient=agenda.patient,
            professional=agenda.staff.professional,
            chair=agenda.staff.chair,
            starts_at=inicio,
            created_by_user_id=agenda.staff.admin.id,
        )
        db_session.add(
            AppointmentEvent(
                clinic_id=agenda.staff.clinic.id,
                appointment_id=turno.id,
                actor_type=ActorType.USER,
                actor_user_id=agenda.staff.admin.id,
                event=AppointmentEventType.CREATED,
                to_status=AppointmentStatus.CONFIRMED,
                payload={},
                slot_starts_at=turno.starts_at,
                slot_ends_at=turno.ends_at,
                professional_id=turno.professional_id,
                chair_id=turno.chair_id,
            )
        )
    await db_session.flush()
    hasta = DIA + timedelta(days=22)

    inicio_t = time.perf_counter()
    ocupacion = await app_client.get(
        "/api/reports/occupancy", params=rango(DIA, hasta), headers=agenda.headers["admin"]
    )
    ausentismo = await app_client.get(
        "/api/reports/absenteeism", params=rango(DIA, hasta), headers=agenda.headers["admin"]
    )
    transcurrido = time.perf_counter() - inicio_t

    assert ocupacion.status_code == ausentismo.status_code == 200
    assert ocupacion.json()["totals"]["appointments"] == VOLUMEN
    assert transcurrido < 2.0, f"reportes lentos: {transcurrido:.2f}s"

    exportacion = await app_client.get(
        "/api/exports/full", params={"format": "csv"}, headers=agenda.headers["admin"]
    )
    paquete = zipfile.ZipFile(io.BytesIO(exportacion.content))
    filas = paquete.read("appointments.csv").decode("utf-8-sig").count("\r\n") - 1
    assert filas == VOLUMEN
