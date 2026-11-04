"""Los reportes se calculan desde eventos, no desde `appointment.status` (C-13, US-050 CA-3)."""

from __future__ import annotations

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import Settings
from tests.appointment_helpers import at, iso, make_agenda
from tests.conftest import MutableClock
from tests.factories import make_patient
from tests.report_helpers import DIA, DIA2, alta, fijar_reloj, rango, reporte, transicion

pytestmark = pytest.mark.integration


async def test_alterar_el_estado_a_mano_no_cambia_el_reporte(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await alta(app_client, agenda, 10)

    await db_session.execute(
        text("UPDATE appointment SET status = 'present' WHERE id = :id"), {"id": turno}
    )

    informe = (await reporte(app_client, agenda, "absenteeism")).json()
    assert informe["totals"]["present"] == 0


async def test_turno_reprogramado_y_cancelado_cuenta_una_vez_con_su_horario_final(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await alta(app_client, agenda, 10)
    movido = await app_client.patch(
        f"/api/appointments/{turno}",
        json={"starts_at": iso(10, days=14)},
        headers=agenda.headers["recepcion"],
    )
    assert movido.status_code == 200, movido.text
    await transicion(app_client, agenda, turno, "cancelled", reason="paciente")

    primer_lunes = (await reporte(app_client, agenda, "cancellations")).json()
    segundo_lunes = (
        await app_client.get(
            "/api/reports/cancellations",
            params=rango(DIA2, DIA2),
            headers=agenda.headers["admin"],
        )
    ).json()
    ambos = (
        await app_client.get(
            "/api/reports/cancellations",
            params=rango(DIA, DIA2),
            headers=agenda.headers["admin"],
        )
    ).json()

    assert primer_lunes["total"] == 0
    assert segundo_lunes["total"] == 1
    assert ambos["total"] == 1


async def test_fusion_de_pacientes_no_borra_la_cancelacion_ni_saca_el_turno_del_reporte(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    """El `updated` de la fusión es el último evento: sella el horario y no tapa el motivo."""
    agenda = await make_agenda(db_session, redis_client, settings)
    turno = await alta(app_client, agenda, 10)
    fijar_reloj(agenda_clock, at(8, 30, days=7))
    await transicion(app_client, agenda, turno, "cancelled", reason="paciente")
    conservado = await make_patient(
        db_session, agenda.staff.clinic, full_name="Conservado Ficticio"
    )

    fusion = await app_client.post(
        f"/api/patients/{agenda.patient.id}/merge",
        json={"into_patient_id": str(conservado.id)},
        headers=agenda.headers["admin"],
    )
    assert fusion.status_code == 200, fusion.text

    informe = (await reporte(app_client, agenda, "cancellations")).json()
    paciente = next(f for f in informe["rows"] if f["reason"] == "paciente")
    assert (paciente["total"], paciente["late"]) == (1, 1)
