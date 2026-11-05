"""`reconcile`/`schedule_new` (C-09, D2): la secuencia de jobs sale del estado actual del turno."""

from __future__ import annotations

from datetime import timedelta

import pytest
from app.models import (
    Appointment,
    AppointmentOrigin,
    AppointmentStatus,
    CancellationReason,
    Clinic,
    DeliveryEventType,
    ReminderStatus,
)
from app.modules.reminders.scheduling import reconcile, schedule_new
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.reminder_helpers import (
    AHORA,
    E,
    Scene,
    W,
    events_of,
    jobs_of,
    make_job,
    make_scene,
    statuses_of,
)

pytestmark = pytest.mark.integration

PENDIENTE = ReminderStatus.SCHEDULED


async def _mover(session: AsyncSession, escena: Scene, nuevo_inicio: object) -> None:
    turno = escena.appointment
    turno.starts_at = nuevo_inicio  # type: ignore[assignment]
    turno.ends_at = turno.starts_at + timedelta(minutes=30)
    turno.occupied_until = turno.ends_at
    await session.flush()


async def _cancelar(session: AsyncSession, turno: Appointment) -> None:
    turno.status = AppointmentStatus.CANCELLED
    turno.cancelled_at = AHORA
    turno.cancellation_reason = CancellationReason.PACIENTE
    await session.flush()


# ------------------------------------------------------------------ alta


async def test_turno_a_cinco_dias_programa_alta_y_los_tres_pasos(db_session: AsyncSession) -> None:
    escena = await make_scene(db_session, starts_in=timedelta(days=5))

    await schedule_new(db_session, escena.appointment, now=AHORA)

    jobs = await jobs_of(db_session, escena.appointment.id)
    assert sorted(jobs) == [
        ("created", "whatsapp"),
        ("t_24h", "whatsapp"),
        ("t_3h", "whatsapp"),
        ("t_72h", "whatsapp"),
    ]
    inicio = escena.appointment.starts_at
    assert jobs[("created", "whatsapp")].scheduled_for == AHORA
    for paso, horas in (("t_72h", 72), ("t_24h", 24), ("t_3h", 3)):
        job = jobs[(paso, "whatsapp")]
        assert job.scheduled_for == inicio - timedelta(hours=horas)
        assert job.available_at == job.scheduled_for
        assert job.status is PENDIENTE and job.attempts == 0
    assert all(j.starts_at_snapshot == inicio for j in jobs.values())
    assert all(j.clinic_id == escena.clinic.id for j in jobs.values())


async def test_turno_a_treinta_horas_omite_el_paso_de_72(db_session: AsyncSession) -> None:
    escena = await make_scene(db_session, starts_in=timedelta(hours=30))

    await schedule_new(db_session, escena.appointment, now=AHORA)

    assert sorted(await jobs_of(db_session, escena.appointment.id)) == [
        ("created", "whatsapp"),
        ("t_24h", "whatsapp"),
        ("t_3h", "whatsapp"),
    ]


async def test_turno_a_dos_horas_solo_tiene_el_alta(db_session: AsyncSession) -> None:
    escena = await make_scene(db_session, starts_in=timedelta(hours=2))

    await schedule_new(db_session, escena.appointment, now=AHORA)

    assert sorted(await jobs_of(db_session, escena.appointment.id)) == [("created", "whatsapp")]


async def test_programar_dos_veces_no_duplica_ni_cambia_nada(db_session: AsyncSession) -> None:
    escena = await make_scene(db_session)
    await schedule_new(db_session, escena.appointment, now=AHORA)
    antes = {
        k: (j.id, j.scheduled_for, j.status)
        for k, j in (await jobs_of(db_session, escena.appointment.id)).items()
    }

    await schedule_new(db_session, escena.appointment, now=AHORA)
    await reconcile(db_session, escena.appointment, now=AHORA)

    despues = {
        k: (j.id, j.scheduled_for, j.status)
        for k, j in (await jobs_of(db_session, escena.appointment.id)).items()
    }
    assert despues == antes
    assert len(despues) == 4


async def test_un_turno_ya_iniciado_no_programa_nada(db_session: AsyncSession) -> None:
    escena = await make_scene(db_session, starts_in=timedelta(minutes=-10))

    await schedule_new(db_session, escena.appointment, now=AHORA)

    assert await jobs_of(db_session, escena.appointment.id) == {}


# ---------------------------------------------------------------- reprogramar


async def test_mover_una_semana_adelante_recalcula_los_pendientes(db_session: AsyncSession) -> None:
    escena = await make_scene(db_session)
    await schedule_new(db_session, escena.appointment, now=AHORA)
    nuevo = escena.appointment.starts_at + timedelta(days=7)

    await _mover(db_session, escena, nuevo)
    await reconcile(db_session, escena.appointment, now=AHORA)

    jobs = await jobs_of(db_session, escena.appointment.id)
    for paso, horas in (("t_72h", 72), ("t_24h", 24), ("t_3h", 3)):
        job = jobs[(paso, "whatsapp")]
        assert job.status is PENDIENTE
        assert job.scheduled_for == nuevo - timedelta(hours=horas)
        assert job.available_at == job.scheduled_for
        assert job.starts_at_snapshot == nuevo


async def test_mover_a_un_horario_cercano_cancela_los_pasos_que_ya_no_son_futuros(
    db_session: AsyncSession,
) -> None:
    escena = await make_scene(db_session)
    await schedule_new(db_session, escena.appointment, now=AHORA)

    await _mover(db_session, escena, AHORA + timedelta(hours=10))
    await reconcile(db_session, escena.appointment, now=AHORA)

    jobs = await jobs_of(db_session, escena.appointment.id)
    assert jobs[("t_72h", "whatsapp")].status is ReminderStatus.CANCELLED
    assert jobs[("t_72h", "whatsapp")].reason == "step_elapsed"
    assert jobs[("t_24h", "whatsapp")].status is ReminderStatus.CANCELLED
    assert jobs[("t_3h", "whatsapp")].status is PENDIENTE
    assert jobs[("t_3h", "whatsapp")].scheduled_for == AHORA + timedelta(hours=7)
    [evento] = await events_of(db_session, jobs[("t_72h", "whatsapp")].id)
    assert evento.event_type is DeliveryEventType.CANCELLED
    assert evento.payload == {"reason": "step_elapsed"}


async def test_un_paso_ya_enviado_no_se_toca_ni_se_recrea(db_session: AsyncSession) -> None:
    escena = await make_scene(db_session)
    await schedule_new(db_session, escena.appointment, now=AHORA)
    viejo = (await jobs_of(db_session, escena.appointment.id))[("t_72h", "whatsapp")]
    await db_session.execute(
        update(type(viejo))
        .where(type(viejo).id == viejo.id)
        .values(status=ReminderStatus.SENT, sent_at=AHORA)
    )

    await _mover(db_session, escena, escena.appointment.starts_at + timedelta(days=7))
    await reconcile(db_session, escena.appointment, now=AHORA)

    jobs = await jobs_of(db_session, escena.appointment.id)
    assert len(jobs) == 4
    assert jobs[("t_72h", "whatsapp")].status is ReminderStatus.SENT
    assert jobs[("t_72h", "whatsapp")].scheduled_for == viejo.scheduled_for


async def test_un_job_sending_no_se_toca(db_session: AsyncSession) -> None:
    escena = await make_scene(db_session)
    await make_job(db_session, escena.appointment, step="t_24h", status=ReminderStatus.SENDING)

    await _cancelar(db_session, escena.appointment)
    await reconcile(db_session, escena.appointment, now=AHORA)

    assert (await statuses_of(db_session, escena.appointment.id)) == {"t_24h/whatsapp": "sending"}


# ----------------------------------------------------------- cancelar / estados


async def test_cancelar_el_turno_cancela_todos_sus_pendientes(db_session: AsyncSession) -> None:
    escena = await make_scene(db_session)
    await schedule_new(db_session, escena.appointment, now=AHORA)

    await _cancelar(db_session, escena.appointment)
    await reconcile(db_session, escena.appointment, now=AHORA)

    estados = await jobs_of(db_session, escena.appointment.id)
    assert {j.status for j in estados.values()} == {ReminderStatus.CANCELLED}
    assert {j.reason for j in estados.values()} == {"appointment_inactive"}


@pytest.mark.parametrize(
    "estado", [AppointmentStatus.PRESENT, AppointmentStatus.ABSENT, AppointmentStatus.NO_SHOW]
)
async def test_un_turno_con_asistencia_registrada_no_conserva_pendientes(
    db_session: AsyncSession, estado: AppointmentStatus
) -> None:
    escena = await make_scene(db_session)
    await schedule_new(db_session, escena.appointment, now=AHORA)

    escena.appointment.status = estado
    await db_session.flush()
    await reconcile(db_session, escena.appointment, now=AHORA)

    assert {j.status for j in (await jobs_of(db_session, escena.appointment.id)).values()} == {
        ReminderStatus.CANCELLED
    }


# ------------------------------------------------------------------- confirmar


async def test_confirmar_un_turno_online_cancela_los_pasos_que_piden_confirmar(
    db_session: AsyncSession,
) -> None:
    escena = await make_scene(
        db_session, status=AppointmentStatus.PENDING, origin=AppointmentOrigin.ONLINE
    )
    await schedule_new(db_session, escena.appointment, now=AHORA)
    assert set((await statuses_of(db_session, escena.appointment.id)).values()) == {"scheduled"}

    escena.appointment.status = AppointmentStatus.CONFIRMED
    await db_session.flush()
    await reconcile(db_session, escena.appointment, now=AHORA)

    assert await statuses_of(db_session, escena.appointment.id) == {
        "created/whatsapp": "cancelled",
        "t_72h/whatsapp": "cancelled",
        "t_24h/whatsapp": "cancelled",
        "t_3h/whatsapp": "scheduled",
    }
    jobs = await jobs_of(db_session, escena.appointment.id)
    assert jobs[("t_72h", "whatsapp")].reason == "confirmed"


async def test_un_turno_online_confirmado_antes_de_programar_solo_recibe_el_paso_de_3_horas(
    db_session: AsyncSession,
) -> None:
    escena = await make_scene(
        db_session, status=AppointmentStatus.CONFIRMED, origin=AppointmentOrigin.ONLINE
    )

    await schedule_new(db_session, escena.appointment, now=AHORA)

    assert sorted(await jobs_of(db_session, escena.appointment.id)) == [("t_3h", "whatsapp")]


async def test_un_turno_de_recepcion_nace_confirmado_y_recibe_los_cuatro(
    db_session: AsyncSession,
) -> None:
    escena = await make_scene(
        db_session, status=AppointmentStatus.CONFIRMED, origin=AppointmentOrigin.RECEPTION
    )

    await schedule_new(db_session, escena.appointment, now=AHORA)
    await reconcile(db_session, escena.appointment, now=AHORA)

    assert await statuses_of(db_session, escena.appointment.id) == {
        "created/whatsapp": "scheduled",
        "t_72h/whatsapp": "scheduled",
        "t_24h/whatsapp": "scheduled",
        "t_3h/whatsapp": "scheduled",
    }


# -------------------------------------------------------- configuración de la clínica


async def test_cambiar_los_pasos_de_la_clinica_ajusta_los_pendientes(
    db_session: AsyncSession,
) -> None:
    escena = await make_scene(db_session)
    await schedule_new(db_session, escena.appointment, now=AHORA)

    await db_session.execute(
        update(Clinic)
        .where(Clinic.id == escena.clinic.id)
        .values(
            reminder_steps=[
                {"offset_h": 48, "channel": "whatsapp"},
                {"offset_h": 3, "channel": "whatsapp"},
                {"offset_h": 24, "channel": "email"},
            ]
        )
    )
    await reconcile(db_session, escena.appointment, now=AHORA)

    assert await statuses_of(db_session, escena.appointment.id) == {
        "created/whatsapp": "scheduled",
        "t_72h/whatsapp": "cancelled",
        "t_24h/whatsapp": "cancelled",
        "t_3h/whatsapp": "scheduled",
        "t_48h/whatsapp": "scheduled",
        "t_24h/email": "scheduled",
    }
    jobs = await jobs_of(db_session, escena.appointment.id)
    assert jobs[("t_72h", "whatsapp")].reason == "step_removed"
    assert jobs[("t_24h", "email")].channel is E
    assert jobs[("t_48h", "whatsapp")].channel is W


async def test_reconcile_no_toca_jobs_de_otro_turno(db_session: AsyncSession) -> None:
    escena = await make_scene(db_session)
    otro = await make_scene(db_session, clinic=escena.clinic)
    await schedule_new(db_session, otro.appointment, now=AHORA)
    antes = await statuses_of(db_session, otro.appointment.id)

    await schedule_new(db_session, escena.appointment, now=AHORA)
    await _cancelar(db_session, escena.appointment)
    await reconcile(db_session, escena.appointment, now=AHORA)

    assert await statuses_of(db_session, otro.appointment.id) == antes
    turnos = (await db_session.execute(select(Appointment.id))).scalars().all()
    assert escena.appointment.id in turnos
