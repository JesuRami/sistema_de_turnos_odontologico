"""Aislamiento por clínica del motor de recordatorios (C-09, regla 4)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from app.models import AppointmentStatus, CancellationReason, ConsentSource, ConsentStatus
from app.modules.reminders.consent import ConsentService
from app.modules.reminders.scheduling import reconcile, schedule_new
from sqlalchemy.ext.asyncio import AsyncSession

from tests.reminder_helpers import AHORA, W, make_scene, statuses_of

pytestmark = pytest.mark.integration

TELEFONO_COMPARTIDO = "+5491155550177"


async def test_cancelar_en_la_clinica_a_no_toca_los_jobs_de_la_clinica_b(
    db_session: AsyncSession,
) -> None:
    a = await make_scene(db_session)
    b = await make_scene(db_session, starts_in=timedelta(days=5))
    await schedule_new(db_session, a.appointment, now=AHORA)
    await schedule_new(db_session, b.appointment, now=AHORA)
    antes = await statuses_of(db_session, b.appointment.id)

    a.appointment.status = AppointmentStatus.CANCELLED
    a.appointment.cancelled_at = AHORA
    a.appointment.cancellation_reason = CancellationReason.PACIENTE
    await db_session.flush()
    await reconcile(db_session, a.appointment, now=AHORA)

    assert set((await statuses_of(db_session, a.appointment.id)).values()) == {"cancelled"}
    assert await statuses_of(db_session, b.appointment.id) == antes
    assert set(antes.values()) == {"scheduled"}


async def test_la_baja_de_un_paciente_no_afecta_a_otro_con_el_mismo_telefono_en_otra_clinica(
    db_session: AsyncSession,
) -> None:
    a = await make_scene(db_session, opt_in=True)
    b = await make_scene(db_session, opt_in=True)
    for escena in (a, b):
        escena.patient.phone_e164 = TELEFONO_COMPARTIDO
    await db_session.flush()
    await schedule_new(db_session, a.appointment, now=AHORA)
    await schedule_new(db_session, b.appointment, now=AHORA)

    await ConsentService(db_session).record(
        a.patient, W, ConsentStatus.OPT_OUT, ConsentSource.WHATSAPP_REPLY
    )

    assert set((await statuses_of(db_session, a.appointment.id)).values()) == {"skipped"}
    assert set((await statuses_of(db_session, b.appointment.id)).values()) == {"scheduled"}
    await db_session.refresh(b.patient)
    assert b.patient.whatsapp_opt_in is True


async def test_el_consentimiento_de_una_clinica_no_se_lee_desde_otra(
    db_session: AsyncSession,
) -> None:
    a = await make_scene(db_session)
    b = await make_scene(db_session)
    await ConsentService(db_session).record(
        a.patient, W, ConsentStatus.OPT_IN, ConsentSource.BOOKING
    )

    desde_b = await ConsentService(db_session).current(b.clinic.id, a.patient.id, W)
    desde_a = await ConsentService(db_session).current(a.clinic.id, a.patient.id, W)

    assert desde_b is None
    assert desde_a is ConsentStatus.OPT_IN
