"""`ConsentService.record` (C-09, D8): único escritor del consentimiento y de su proyección."""

from __future__ import annotations

import pytest
from app.models import (
    Consent,
    ConsentSource,
    ConsentStatus,
    DeliveryEventType,
    Patient,
    ReminderStatus,
)
from app.modules.reminders.consent import ConsentService
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_patient, make_user
from tests.reminder_helpers import E, W, events_of, jobs_of, make_job, make_scene

pytestmark = pytest.mark.integration


async def _filas(session: AsyncSession, patient: Patient) -> list[Consent]:
    return list(
        (
            await session.execute(
                select(Consent)
                .where(Consent.patient_id == patient.id)
                .order_by(Consent.changed_at)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )


async def test_opt_in_agrega_una_fila_con_fuente_y_activa_el_flag(db_session: AsyncSession) -> None:
    escena = await make_scene(db_session)
    usuario = await make_user(db_session, escena.clinic)

    cambio = await ConsentService(db_session).record(
        escena.patient, W, ConsentStatus.OPT_IN, ConsentSource.RECEPTION, user_id=usuario.id
    )

    assert cambio is True
    assert escena.patient.whatsapp_opt_in is True
    [fila] = await _filas(db_session, escena.patient)
    assert (fila.channel, fila.status, fila.source) == (
        W,
        ConsentStatus.OPT_IN,
        ConsentSource.RECEPTION,
    )
    assert fila.changed_by_user_id == usuario.id
    assert fila.clinic_id == escena.clinic.id


async def test_repetir_el_mismo_estado_no_agrega_fila(db_session: AsyncSession) -> None:
    escena = await make_scene(db_session)
    servicio = ConsentService(db_session)
    await servicio.record(escena.patient, W, ConsentStatus.OPT_IN, ConsentSource.BOOKING)

    repetido = await servicio.record(escena.patient, W, ConsentStatus.OPT_IN, ConsentSource.BOOKING)

    assert repetido is False
    assert len(await _filas(db_session, escena.patient)) == 1


async def test_la_primera_baja_de_quien_nunca_dio_opt_in_queda_registrada(
    db_session: AsyncSession,
) -> None:
    escena = await make_scene(db_session)

    cambio = await ConsentService(db_session).record(
        escena.patient, W, ConsentStatus.OPT_OUT, ConsentSource.WHATSAPP_REPLY
    )

    assert cambio is True
    assert escena.patient.whatsapp_opt_in is False
    [fila] = await _filas(db_session, escena.patient)
    assert fila.status is ConsentStatus.OPT_OUT


async def test_la_baja_salta_solo_los_jobs_pendientes_de_ese_paciente_y_canal(
    db_session: AsyncSession,
) -> None:
    escena = await make_scene(db_session, opt_in=True)
    otro = await make_scene(db_session, clinic=escena.clinic, opt_in=True)
    ajena = await make_scene(db_session, opt_in=True)
    pendiente_24 = await make_job(db_session, escena.appointment, step="t_24h")
    pendiente_3 = await make_job(db_session, escena.appointment, step="t_3h")
    email = await make_job(db_session, escena.appointment, step="t_24h", channel=E)
    enviado = await make_job(
        db_session, escena.appointment, step="t_72h", status=ReminderStatus.SENT
    )
    de_otro = await make_job(db_session, otro.appointment)
    de_otra_clinica = await make_job(db_session, ajena.appointment)

    await ConsentService(db_session).record(
        escena.patient, W, ConsentStatus.OPT_OUT, ConsentSource.WHATSAPP_REPLY
    )

    propios = await jobs_of(db_session, escena.appointment.id)
    assert propios[("t_24h", "whatsapp")].status is ReminderStatus.SKIPPED
    assert propios[("t_24h", "whatsapp")].reason == "no_consent"
    assert propios[("t_3h", "whatsapp")].status is ReminderStatus.SKIPPED
    assert propios[("t_24h", "email")].status is ReminderStatus.SCHEDULED
    assert propios[("t_72h", "whatsapp")].status is ReminderStatus.SENT
    for job in (de_otro, de_otra_clinica):
        assert (await jobs_of(db_session, job.appointment_id))[("t_24h", "whatsapp")].status is (
            ReminderStatus.SCHEDULED
        )
    [evento] = await events_of(db_session, pendiente_24.id)
    assert evento.event_type is DeliveryEventType.SKIPPED
    assert evento.payload == {"reason": "no_consent"}
    assert len(await events_of(db_session, pendiente_3.id)) == 1
    assert await events_of(db_session, email.id) == []
    assert await events_of(db_session, enviado.id) == []


async def test_la_baja_de_email_no_toca_el_flag_de_whatsapp(db_session: AsyncSession) -> None:
    escena = await make_scene(db_session, opt_in=True, email="paciente.ficticio@example.com")
    await make_job(db_session, escena.appointment, channel=E)
    await make_job(db_session, escena.appointment, step="t_3h")

    await ConsentService(db_session).record(
        escena.patient,
        E,
        ConsentStatus.OPT_OUT,
        ConsentSource.RECEPTION,
        user_id=(await make_user(db_session, escena.clinic)).id,
    )

    assert escena.patient.whatsapp_opt_in is True
    jobs = await jobs_of(db_session, escena.appointment.id)
    assert jobs[("t_24h", "email")].status is ReminderStatus.SKIPPED
    assert jobs[("t_3h", "whatsapp")].status is ReminderStatus.SCHEDULED


async def test_si_la_transaccion_revierte_no_cambia_nada(db_session: AsyncSession) -> None:
    escena = await make_scene(db_session, opt_in=True)
    await make_job(db_session, escena.appointment)

    with pytest.raises(RuntimeError):
        async with db_session.begin_nested():
            await ConsentService(db_session).record(
                escena.patient, W, ConsentStatus.OPT_OUT, ConsentSource.WHATSAPP_REPLY
            )
            raise RuntimeError("falla posterior en la misma transacción")
    await db_session.refresh(escena.patient)

    assert escena.patient.whatsapp_opt_in is True
    assert await _filas(db_session, escena.patient) == []
    jobs = await jobs_of(db_session, escena.appointment.id)
    assert jobs[("t_24h", "whatsapp")].status is ReminderStatus.SCHEDULED


async def test_recepcion_exige_usuario(db_session: AsyncSession) -> None:
    escena = await make_scene(db_session)

    with pytest.raises(ValueError, match="reception"):
        await ConsentService(db_session).record(
            escena.patient, W, ConsentStatus.OPT_IN, ConsentSource.RECEPTION
        )


async def test_paridad_ultimo_consentimiento_de_whatsapp_y_flag(db_session: AsyncSession) -> None:
    escena = await make_scene(db_session)
    servicio = ConsentService(db_session)
    otros = [await make_patient(db_session, escena.clinic) for _ in range(3)]
    for paciente in (escena.patient, *otros):
        await servicio.record(paciente, W, ConsentStatus.OPT_IN, ConsentSource.BOOKING)
    await servicio.record(otros[0], W, ConsentStatus.OPT_OUT, ConsentSource.WHATSAPP_REPLY)
    await servicio.record(otros[1], W, ConsentStatus.OPT_OUT, ConsentSource.WHATSAPP_REPLY)
    await servicio.record(otros[1], W, ConsentStatus.OPT_IN, ConsentSource.BOOKING)

    divergentes = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM patient p JOIN LATERAL ("
                "  SELECT status FROM consent c WHERE c.patient_id = p.id "
                "  AND c.channel = 'whatsapp' ORDER BY changed_at DESC LIMIT 1"
                ") u ON true WHERE (u.status = 'opt_in') <> p.whatsapp_opt_in"
            )
        )
    ).scalar_one()

    assert divergentes == 0
    total = await db_session.scalar(select(func.count()).select_from(Consent))
    assert total is not None and total >= 7
