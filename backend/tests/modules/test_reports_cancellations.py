"""Reporte de cancelaciones por motivo, con corte tardía / en ventana (C-13, RN-CX-04)."""

from __future__ import annotations

import httpx
import pytest
from app.core.settings import Settings
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tests.appointment_helpers import at, make_agenda
from tests.conftest import MutableClock
from tests.report_helpers import alta, fijar_reloj, reporte, transicion

pytestmark = pytest.mark.integration


async def test_cuenta_por_motivo_y_separa_tardias_de_en_ventana(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    en_ventana = await alta(app_client, agenda, 11)
    clinica = await alta(app_client, agenda, 12)
    tardia = await alta(app_client, agenda, 9)
    await transicion(app_client, agenda, en_ventana, "cancelled", reason="paciente")
    await transicion(app_client, agenda, clinica, "cancelled", reason="clinica")
    fijar_reloj(agenda_clock, at(8, 0, days=7))
    await transicion(app_client, agenda, tardia, "cancelled", reason="paciente")

    informe = (await reporte(app_client, agenda, "cancellations")).json()

    por_motivo = {f["reason"]: f for f in informe["rows"]}
    assert set(por_motivo) == {"paciente", "profesional", "clinica", "bloqueo", "otro"}
    assert (por_motivo["paciente"]["total"], por_motivo["paciente"]["late"]) == (2, 1)
    assert por_motivo["paciente"]["in_window"] == 1
    assert por_motivo["clinica"]["total"] == 1
    assert por_motivo["profesional"]["total"] == por_motivo["otro"]["total"] == 0
    assert informe["total"] == 3
