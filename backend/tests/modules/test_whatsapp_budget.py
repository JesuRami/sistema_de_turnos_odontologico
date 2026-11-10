"""Alerta de costo mensual de WhatsApp (C-14, D8; SU-07). Postgres y Redis reales.

Umbral por la política `whatsapp_monthly_alert_usd`; gasto del mes local sobre `delivery_event`
`sent` de jobs de WhatsApp (misma fuente que el reporte de C-10). Sin corte de envíos.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
from app.core.settings import Settings
from app.models import (
    AgendaConfigEvent,
    DeliveryEvent,
    DeliveryEventType,
    ReminderChannel,
    ReminderJob,
    ReminderStatus,
)
from app.modules.reports.budget import budget_status, month_bounds
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.agenda_helpers import Staff, make_staff
from tests.conftest import MutableClock
from tests.factories import make_appointment, make_patient

pytestmark = pytest.mark.integration

URL = "/api/reports/whatsapp/budget"
POLICIES = "/api/clinic/policies"
AHORA = datetime(2030, 1, 20, 15, 0, tzinfo=UTC)
BA = ZoneInfo("America/Argentina/Buenos_Aires")


@pytest.fixture()
def reloj(app_instance: object) -> MutableClock:
    from app.common.clock import get_now

    clock = MutableClock(current=AHORA)
    app_instance.dependency_overrides[get_now] = lambda: clock.current  # type: ignore[attr-defined]
    return clock


async def _enviado(
    db: AsyncSession,
    staff: Staff,
    sent_at: datetime,
    cost: int,
    channel: ReminderChannel = ReminderChannel.WHATSAPP,
) -> None:
    paciente = await make_patient(db, staff.clinic, full_name="Paciente Costo Ficticio")
    turno = await make_appointment(
        db,
        staff.clinic,
        patient=paciente,
        professional=staff.professional,
        chair=staff.chair,
        starts_at=sent_at + timedelta(days=2, minutes=secrets.randbelow(10_000)),
    )
    job = ReminderJob(
        clinic_id=staff.clinic.id,
        appointment_id=turno.id,
        step="t_24h",
        channel=channel,
        scheduled_for=sent_at,
        available_at=sent_at,
        starts_at_snapshot=turno.starts_at,
        status=ReminderStatus.SENT,
        sent_at=sent_at,
        provider_message_id="wamid.COSTO-" + secrets.token_hex(6),
        cost_micros=cost,
    )
    db.add(job)
    await db.flush()
    db.add(
        DeliveryEvent(
            clinic_id=staff.clinic.id,
            reminder_job_id=job.id,
            event_type=DeliveryEventType.SENT,
            payload={"attempt": 1, "kind": "template", "cost_micros": cost},
            occurred_at=sent_at,
        )
    )
    await db.flush()


async def test_sin_umbral_la_alerta_esta_desactivada(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    reloj: MutableClock,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    await _enviado(db_session, staff, AHORA - timedelta(days=1), 500_000)

    cuerpo = (await app_client.get(URL, headers=staff.headers["admin"])).json()

    assert cuerpo == {
        "month": "2030-01",
        "currency": "USD",
        "spent_usd": "0.500000",
        "threshold_usd": None,
        "used_pct": None,
        "status": "disabled",
    }


async def test_umbral_por_politica_auditado_y_estados(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    reloj: MutableClock,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    admin = staff.headers["admin"]

    politica = await app_client.patch(
        POLICIES, json={"whatsapp_monthly_alert_usd": "1"}, headers=admin
    )
    assert politica.status_code == 200, politica.text
    assert politica.json()["whatsapp_monthly_alert_usd"] == "1.000000"
    eventos = (
        await db_session.execute(
            select(AgendaConfigEvent.changes).where(AgendaConfigEvent.clinic_id == staff.clinic.id)
        )
    ).scalars()
    assert any("whatsapp_monthly_alert_micros" in c for c in eventos)

    await _enviado(db_session, staff, AHORA - timedelta(days=2), 850_000)
    warning = (await app_client.get(URL, headers=admin)).json()
    await _enviado(db_session, staff, AHORA - timedelta(hours=1), 300_000)
    excedido = (await app_client.get(URL, headers=admin)).json()

    assert (warning["status"], warning["used_pct"]) == ("warning", 85.0)
    assert (excedido["status"], excedido["spent_usd"]) == ("exceeded", "1.150000")


async def test_solo_cuenta_whatsapp_del_mes_local_en_curso(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    reloj: MutableClock,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    admin = staff.headers["admin"]
    await app_client.patch(POLICIES, json={"whatsapp_monthly_alert_usd": "10"}, headers=admin)
    await _enviado(db_session, staff, AHORA - timedelta(days=1), 1_000_000)
    await _enviado(db_session, staff, AHORA - timedelta(days=1), 9_000_000, ReminderChannel.EMAIL)
    # 31/12 22:00 en Buenos Aires = 01/01 01:00 UTC: todavía es diciembre local.
    await _enviado(db_session, staff, datetime(2030, 1, 1, 1, 0, tzinfo=UTC), 9_000_000)

    cuerpo = (await app_client.get(URL, headers=admin)).json()

    assert (cuerpo["spent_usd"], cuerpo["status"], cuerpo["used_pct"]) == ("1.000000", "ok", 10.0)


async def test_cero_apaga_la_alerta_y_validacion_de_la_politica(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    reloj: MutableClock,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    admin = staff.headers["admin"]
    await app_client.patch(POLICIES, json={"whatsapp_monthly_alert_usd": "5"}, headers=admin)

    apagada = await app_client.patch(
        POLICIES, json={"whatsapp_monthly_alert_usd": "0"}, headers=admin
    )
    negativa = await app_client.patch(
        POLICIES, json={"whatsapp_monthly_alert_usd": "-1"}, headers=admin
    )
    nula = await app_client.patch(
        POLICIES, json={"whatsapp_monthly_alert_usd": None}, headers=admin
    )
    recepcion = await app_client.get(URL, headers=staff.headers["recepcion"])

    assert apagada.json()["whatsapp_monthly_alert_usd"] is None
    assert (await app_client.get(URL, headers=admin)).json()["status"] == "disabled"
    assert negativa.status_code == 422
    assert nula.status_code == 422
    assert recepcion.status_code == 403


def test_limites_del_mes_local() -> None:
    inicio, fin = month_bounds(datetime(2030, 12, 31, 12, 0, tzinfo=UTC), BA)
    assert (inicio.isoformat(), fin.isoformat()) == (
        "2030-12-01T00:00:00-03:00",
        "2031-01-01T00:00:00-03:00",
    )


@pytest.mark.parametrize(
    ("gastado", "umbral", "estado"),
    [(0, None, "disabled"), (79, 100, "ok"), (80, 100, "warning"), (100, 100, "exceeded")],
)
def test_estado_por_porcentaje(gastado: int, umbral: int | None, estado: str) -> None:
    assert budget_status(gastado, umbral)[0] == estado
