"""Validación previa al envío: el motor no manda a quien no corresponde (C-09, D5)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from app.core.settings import Settings
from app.models import (
    Appointment,
    AppointmentStatus,
    CancellationReason,
    Consent,
    ConsentSource,
    ConsentStatus,
    DeliveryEventType,
    NotificationTemplate,
    ReminderChannel,
    ReminderStatus,
)
from app.modules.reminders import dispatch
from app.modules.reminders.dispatch import run_tick
from app.modules.reminders.senders.fake import FakeSender
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.reminder_helpers import (
    AHORA,
    commit_job,
    commit_scene,
    dispatch_settings,
    read_events,
    read_jobs,
)

pytestmark = pytest.mark.integration

VENCIDO = AHORA - timedelta(minutes=1)
W = ReminderChannel.WHATSAPP
E = ReminderChannel.EMAIL


def _senders() -> dict[ReminderChannel, FakeSender]:
    return {W: FakeSender(W), E: FakeSender(E)}


async def _tick(maker: async_sessionmaker[AsyncSession], senders: Any, settings: Settings) -> Any:
    return await run_tick(maker, senders, dispatch_settings(settings), now=lambda: AHORA)


async def _unico(maker: async_sessionmaker[AsyncSession], escena: Any, **clave: str) -> Any:
    jobs = await read_jobs(maker, escena.appointment.id)
    return jobs[(clave.get("step", "t_24h"), clave.get("channel", "whatsapp"))]


async def _mutar_turno(
    maker: async_sessionmaker[AsyncSession], turno_id: Any, **valores: Any
) -> None:
    async with maker() as session:
        await session.execute(
            update(Appointment).where(Appointment.id == turno_id).values(**valores)
        )
        await session.commit()


async def test_un_turno_cancelado_cancela_el_job_sin_enviar(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True)
    await commit_job(rem_maker, escena.appointment, scheduled_for=VENCIDO)
    await _mutar_turno(
        rem_maker,
        escena.appointment.id,
        status=AppointmentStatus.CANCELLED,
        cancelled_at=AHORA,
        cancellation_reason=CancellationReason.PACIENTE,
    )
    senders = _senders()

    await _tick(rem_maker, senders, settings)

    job = await _unico(rem_maker, escena)
    assert (job.status, job.reason) == (ReminderStatus.CANCELLED, "appointment_inactive")
    assert senders[W].sent == []
    [evento] = await read_events(rem_maker, job.id)
    assert evento.event_type is DeliveryEventType.CANCELLED


async def test_un_turno_ya_iniciado_se_salta_y_nunca_queda_sent(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True, starts_in=timedelta(minutes=-10))
    await commit_job(rem_maker, escena.appointment, step="t_3h", scheduled_for=VENCIDO)
    senders = _senders()

    await _tick(rem_maker, senders, settings)

    job = await _unico(rem_maker, escena, step="t_3h")
    assert (job.status, job.reason) == (ReminderStatus.SKIPPED, "appointment_started")
    assert senders[W].sent == []


async def test_sin_opt_in_de_whatsapp_se_salta(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=False)
    await commit_job(rem_maker, escena.appointment, scheduled_for=VENCIDO)
    senders = _senders()

    await _tick(rem_maker, senders, settings)

    job = await _unico(rem_maker, escena)
    assert (job.status, job.reason) == (ReminderStatus.SKIPPED, "no_consent")
    assert senders[W].sent == []
    [evento] = await read_events(rem_maker, job.id)
    assert (evento.event_type, evento.payload) == (
        DeliveryEventType.SKIPPED,
        {"reason": "no_consent"},
    )


async def test_el_email_se_envia_sin_registro_y_se_salta_con_baja_vigente(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    libre = await commit_scene(rem_maker, email="libre.ficticio@example.com")
    baja = await commit_scene(rem_maker, email="baja.ficticia@example.com")
    for escena in (libre, baja):
        await commit_job(rem_maker, escena.appointment, channel=E, scheduled_for=VENCIDO)
    async with rem_maker() as session:
        session.add_all(
            [
                Consent(
                    clinic_id=baja.clinic.id,
                    patient_id=baja.patient.id,
                    channel=E,
                    status=ConsentStatus.OPT_IN,
                    source=ConsentSource.BOOKING,
                ),
                Consent(
                    clinic_id=baja.clinic.id,
                    patient_id=baja.patient.id,
                    channel=E,
                    status=ConsentStatus.OPT_OUT,
                    source=ConsentSource.WHATSAPP_REPLY,
                ),
            ]
        )
        await session.commit()
    senders = _senders()

    await _tick(rem_maker, senders, settings)

    assert (await _unico(rem_maker, libre, channel="email")).status is ReminderStatus.SENT
    job_baja = await _unico(rem_maker, baja, channel="email")
    assert (job_baja.status, job_baja.reason) == (ReminderStatus.SKIPPED, "no_consent")
    assert [m.to for m in senders[E].sent] == ["libre.ficticio@example.com"]


async def test_un_job_de_email_sin_direccion_se_salta_por_falta_de_destinatario(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True)  # tiene teléfono, no email
    await commit_job(rem_maker, escena.appointment, channel=E, scheduled_for=VENCIDO)
    senders = _senders()

    await _tick(rem_maker, senders, settings)

    job = await _unico(rem_maker, escena, channel="email")
    assert (job.status, job.reason) == (ReminderStatus.SKIPPED, "no_recipient")
    assert senders[E].sent == []


@pytest.mark.parametrize("modo", ["inactiva", "ausente"])
async def test_sin_plantilla_activa_el_job_falla_y_escala_al_email(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings, modo: str
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True, email="paciente.ficticio@example.com")
    await commit_job(rem_maker, escena.appointment, scheduled_for=VENCIDO)
    async with rem_maker() as session:
        filtro = (
            NotificationTemplate.clinic_id == escena.clinic.id,
            NotificationTemplate.channel == W,
            NotificationTemplate.step == "t_24h",
        )
        if modo == "inactiva":
            await session.execute(update(NotificationTemplate).where(*filtro).values(active=False))
        else:
            await session.execute(delete(NotificationTemplate).where(*filtro))
        await session.commit()
    senders = _senders()

    await _tick(rem_maker, senders, settings)

    jobs = await read_jobs(rem_maker, escena.appointment.id)
    assert (jobs[("t_24h", "whatsapp")].status, jobs[("t_24h", "whatsapp")].reason) == (
        ReminderStatus.FAILED,
        "template_inactive",
    )
    assert senders[W].sent == []
    # el escalado crea el job de email del mismo paso y el mismo tick ya lo envía
    assert jobs[("t_24h", "email")].status is ReminderStatus.SENT
    tipos = [e.event_type for e in await read_events(rem_maker, jobs[("t_24h", "whatsapp")].id)]
    assert tipos == [DeliveryEventType.FAILED, DeliveryEventType.ESCALATED]


async def test_si_el_horario_cambio_se_reconcilia_y_no_se_envia_con_la_hora_vieja(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True)
    snapshot_viejo = escena.appointment.starts_at - timedelta(hours=1)
    await commit_job(
        rem_maker,
        escena.appointment,
        scheduled_for=VENCIDO,
        starts_at_snapshot=snapshot_viejo,
    )
    senders = _senders()

    await _tick(rem_maker, senders, settings)

    job = await _unico(rem_maker, escena)
    assert senders[W].sent == []
    assert job.status is ReminderStatus.SCHEDULED
    assert job.starts_at_snapshot == escena.appointment.starts_at
    assert job.scheduled_for == escena.appointment.starts_at - timedelta(hours=24)


async def test_un_turno_cancelado_entre_el_reclamo_y_el_envio_no_envia(
    rem_maker: async_sessionmaker[AsyncSession],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True)
    await commit_job(rem_maker, escena.appointment, scheduled_for=VENCIDO)
    original = dispatch._claim_batch

    async def _claim_y_cancela(*args: Any, **kwargs: Any) -> Any:
        reclamados = await original(*args, **kwargs)
        await _mutar_turno(
            rem_maker,
            escena.appointment.id,
            status=AppointmentStatus.CANCELLED,
            cancelled_at=AHORA,
            cancellation_reason=CancellationReason.PACIENTE,
        )
        return reclamados

    monkeypatch.setattr(dispatch, "_claim_batch", _claim_y_cancela)
    senders = _senders()

    await _tick(rem_maker, senders, settings)

    job = await _unico(rem_maker, escena)
    assert (job.status, job.reason) == (ReminderStatus.CANCELLED, "appointment_inactive")
    assert senders[W].sent == []
    assert job.attempts == 1  # el intento ya se había reclamado
