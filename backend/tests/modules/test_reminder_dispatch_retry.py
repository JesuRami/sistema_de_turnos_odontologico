"""Envío, reintentos con backoff, escalado a email, trazabilidad y costo (C-09, D4/D7)."""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Any

import pytest
from app.core.settings import Settings
from app.models import (
    Consent,
    ConsentSource,
    ConsentStatus,
    DeliveryEventType,
    ReminderChannel,
    ReminderJob,
    ReminderStatus,
)
from app.modules.reminders.dispatch import run_tick
from app.modules.reminders.senders.base import SendError
from app.modules.reminders.senders.fake import FakeSender
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.conftest import MutableClock
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
NOMBRE_PACIENTE = "Paciente Ficticio Uno"
EMAIL = "paciente.ficticio@example.com"


def _senders() -> dict[ReminderChannel, FakeSender]:
    return {W: FakeSender(W), E: FakeSender(E)}


class Tick:
    """Corre ticks con un reloj mutable sobre los mismos senders."""

    def __init__(
        self, maker: async_sessionmaker[AsyncSession], settings: Settings, **cambios: Any
    ) -> None:
        self.maker = maker
        self.settings = dispatch_settings(settings, **cambios)
        self.clock = MutableClock(current=AHORA)
        self.senders = _senders()

    async def __call__(self) -> Any:
        return await run_tick(self.maker, self.senders, self.settings, now=self.clock)


async def _job(maker: async_sessionmaker[AsyncSession], escena: Any, **clave: str) -> ReminderJob:
    jobs = await read_jobs(maker, escena.appointment.id)
    return jobs[(clave.get("step", "t_24h"), clave.get("channel", "whatsapp"))]


async def test_un_envio_exitoso_guarda_id_hora_costo_y_evento(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True)
    await commit_job(rem_maker, escena.appointment, scheduled_for=VENCIDO)
    tick = Tick(rem_maker, settings, REMINDER_COST_WHATSAPP_MICROS=12500)

    stats = await tick()

    job = await _job(rem_maker, escena)
    assert job.status is ReminderStatus.SENT
    assert job.provider_message_id == "fake-1"
    assert job.sent_at == AHORA
    assert job.cost_micros == 12500
    assert (job.attempts, job.last_error, job.template_id is not None) == (1, None, True)
    [evento] = await read_events(rem_maker, job.id)
    assert evento.event_type is DeliveryEventType.SENT
    assert evento.payload == {"attempt": 1, "kind": "template"}
    assert stats.sent == 1


async def test_el_mensaje_enviado_lleva_la_plantilla_el_destino_y_el_link_firmado(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True)
    await commit_job(rem_maker, escena.appointment, scheduled_for=VENCIDO)
    tick = Tick(rem_maker, settings)

    await tick()

    [mensaje] = tick.senders[W].sent
    assert mensaje.to == escena.patient.phone_e164
    assert mensaje.template_name == "recordatorio_24h_v1"
    assert mensaje.locale == "es_AR"
    assert mensaje.params["nombre"] == "Paciente"  # solo el nombre de pila
    assert mensaje.params["link"].startswith("http://localhost:5173/g/v1.")
    assert mensaje.params["link"] in mensaje.body
    assert "{{" not in mensaje.body and "Paciente Ficticio Uno" not in mensaje.body


async def test_exito_en_el_segundo_intento(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True)
    await commit_job(rem_maker, escena.appointment, scheduled_for=VENCIDO)
    tick = Tick(rem_maker, settings)
    tick.senders[W].failures.append(SendError("timeout", retryable=True))

    await tick()
    tras_el_primero = await _job(rem_maker, escena)
    tick.clock.advance(minutes=6)
    await tick()

    assert tras_el_primero.status is ReminderStatus.SCHEDULED
    assert tras_el_primero.attempts == 1 and tras_el_primero.last_error == "timeout"
    assert tras_el_primero.available_at == AHORA + timedelta(minutes=5)
    assert tras_el_primero.scheduled_for == VENCIDO  # la hora original se conserva
    final = await _job(rem_maker, escena)
    assert (final.status, final.attempts) == (ReminderStatus.SENT, 2)
    tipos = [e.event_type for e in await read_events(rem_maker, final.id)]
    assert tipos == [DeliveryEventType.ATTEMPT_FAILED, DeliveryEventType.SENT]


async def test_tres_fallos_dejan_el_job_failed_con_backoff_de_5_y_30_minutos(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True)  # sin email: no hay escalado
    await commit_job(rem_maker, escena.appointment, scheduled_for=VENCIDO)
    tick = Tick(rem_maker, settings)
    tick.senders[W].failures.extend(SendError("timeout", retryable=True) for _ in range(3))

    await tick()
    primero = await _job(rem_maker, escena)
    tick.clock.advance(minutes=4)
    await tick()  # todavía en backoff: no reclama
    sin_cambios = await _job(rem_maker, escena)
    tick.clock.advance(minutes=2)
    await tick()
    segundo = await _job(rem_maker, escena)
    tick.clock.advance(minutes=31)
    await tick()
    final = await _job(rem_maker, escena)

    assert primero.available_at == AHORA + timedelta(minutes=5)
    assert sin_cambios.attempts == 1
    assert segundo.attempts == 2
    assert segundo.available_at == AHORA + timedelta(minutes=6) + timedelta(minutes=30)
    assert (final.status, final.attempts, final.reason) == (
        ReminderStatus.FAILED,
        3,
        "send_failed",
    )
    assert final.last_error == "timeout"
    tipos = [e.event_type for e in await read_events(rem_maker, final.id)]
    assert tipos == [DeliveryEventType.ATTEMPT_FAILED] * 3 + [DeliveryEventType.FAILED]
    assert tick.senders[W].sent == []


async def test_el_tercer_fallo_escala_al_email_del_mismo_paso(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True, email=EMAIL)
    await commit_job(rem_maker, escena.appointment, scheduled_for=VENCIDO)
    tick = Tick(rem_maker, settings, REMINDER_MAX_ATTEMPTS=1)
    tick.senders[W].failures.append(SendError("timeout", retryable=True))

    await tick()  # falla, escala, y el mismo tick drena el email

    jobs = await read_jobs(rem_maker, escena.appointment.id)
    assert jobs[("t_24h", "whatsapp")].status is ReminderStatus.FAILED
    email = jobs[("t_24h", "email")]
    assert email.status is ReminderStatus.SENT
    [enviado] = tick.senders[E].sent
    assert enviado.to == EMAIL and enviado.template_name == "email_recordatorio_24h_v1"
    assert enviado.subject
    tipos = [e.event_type for e in await read_events(rem_maker, jobs[("t_24h", "whatsapp")].id)]
    assert tipos == [
        DeliveryEventType.ATTEMPT_FAILED,
        DeliveryEventType.FAILED,
        DeliveryEventType.ESCALATED,
    ]


@pytest.mark.parametrize("caso", ["sin_email", "baja_de_email"])
async def test_sin_email_o_con_baja_no_hay_escalado(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings, caso: str
) -> None:
    escena = await commit_scene(
        rem_maker, opt_in=True, email=EMAIL if caso == "baja_de_email" else None
    )
    await commit_job(rem_maker, escena.appointment, scheduled_for=VENCIDO)
    if caso == "baja_de_email":
        async with rem_maker() as session:
            session.add(
                Consent(
                    clinic_id=escena.clinic.id,
                    patient_id=escena.patient.id,
                    channel=E,
                    status=ConsentStatus.OPT_OUT,
                    source=ConsentSource.WHATSAPP_REPLY,
                )
            )
            await session.commit()
    tick = Tick(rem_maker, settings, REMINDER_MAX_ATTEMPTS=1)
    tick.senders[W].failures.append(SendError("timeout", retryable=True))

    await tick()

    jobs = await read_jobs(rem_maker, escena.appointment.id)
    assert list(jobs) == [("t_24h", "whatsapp")]
    assert jobs[("t_24h", "whatsapp")].status is ReminderStatus.FAILED


async def test_un_error_no_reintentable_falla_al_primer_intento_y_escala(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True, email=EMAIL)
    await commit_job(rem_maker, escena.appointment, scheduled_for=VENCIDO)
    tick = Tick(rem_maker, settings)
    tick.senders[W].failures.append(SendError("recipient_invalid", retryable=False))

    await tick()

    jobs = await read_jobs(rem_maker, escena.appointment.id)
    whatsapp = jobs[("t_24h", "whatsapp")]
    assert (whatsapp.status, whatsapp.attempts, whatsapp.reason, whatsapp.last_error) == (
        ReminderStatus.FAILED,
        1,
        "provider_rejected",
        "recipient_invalid",
    )
    assert jobs[("t_24h", "email")].status is ReminderStatus.SENT


async def test_una_excepcion_inesperada_del_proveedor_se_trata_como_transitoria(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    escena = await commit_scene(rem_maker, opt_in=True)
    await commit_job(rem_maker, escena.appointment, scheduled_for=VENCIDO)
    tick = Tick(rem_maker, settings)

    async def _explota(message: Any) -> Any:
        raise RuntimeError(f"falla con datos de {message.to}")

    tick.senders[W].send = _explota  # type: ignore[method-assign]

    await tick()

    job = await _job(rem_maker, escena)
    assert (job.status, job.attempts, job.last_error) == (
        ReminderStatus.SCHEDULED,
        1,
        "unexpected_error",
    )


async def test_una_plantilla_con_variables_desconocidas_falla_sin_reintentar(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    from app.models import NotificationTemplate
    from sqlalchemy import update

    escena = await commit_scene(rem_maker, opt_in=True)
    await commit_job(rem_maker, escena.appointment, scheduled_for=VENCIDO)
    async with rem_maker() as session:
        await session.execute(
            update(NotificationTemplate)
            .where(
                NotificationTemplate.clinic_id == escena.clinic.id,
                NotificationTemplate.step == "t_24h",
            )
            .values(body_preview="Hola {{nombre}} {{direccion}}")
        )
        await session.commit()
    tick = Tick(rem_maker, settings)

    await tick()

    job = await _job(rem_maker, escena)
    assert (job.status, job.attempts, job.last_error) == (
        ReminderStatus.FAILED,
        1,
        "template_variables",
    )
    assert tick.senders[W].sent == []


async def test_el_costo_se_agrega_por_clinica_y_paso(
    rem_maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    a1 = await commit_scene(rem_maker, opt_in=True)
    a2 = await commit_scene(rem_maker, opt_in=True)
    b1 = await commit_scene(rem_maker, opt_in=True)
    await commit_job(rem_maker, a1.appointment, step="t_24h", scheduled_for=VENCIDO)
    await commit_job(rem_maker, a1.appointment, step="t_3h", scheduled_for=VENCIDO)
    await commit_job(rem_maker, b1.appointment, step="t_24h", scheduled_for=VENCIDO)
    # a2 pertenece a otra clínica distinta a a1 y a b1: su 24 h cuenta para su propia clínica
    await commit_job(rem_maker, a2.appointment, step="t_24h", scheduled_for=VENCIDO)
    tick = Tick(rem_maker, settings, REMINDER_COST_WHATSAPP_MICROS=1000)

    await tick()

    async with rem_maker() as session:
        filas = (
            await session.execute(
                select(
                    ReminderJob.clinic_id,
                    ReminderJob.step,
                    func.count(),
                    func.sum(ReminderJob.cost_micros),
                )
                .where(ReminderJob.status == ReminderStatus.SENT)
                .group_by(ReminderJob.clinic_id, ReminderJob.step)
            )
        ).all()
    por_clave: dict[tuple[uuid.UUID, str], tuple[int, int]] = {
        (f[0], f[1]): (f[2], int(f[3])) for f in filas
    }
    assert por_clave == {
        (a1.clinic.id, "t_24h"): (1, 1000),
        (a1.clinic.id, "t_3h"): (1, 1000),
        (b1.clinic.id, "t_24h"): (1, 1000),
        (a2.clinic.id, "t_24h"): (1, 1000),
    }


async def test_ni_los_logs_ni_last_error_ni_los_eventos_tienen_pii(
    rem_maker: async_sessionmaker[AsyncSession],
    settings: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    escena = await commit_scene(rem_maker, opt_in=True, email=EMAIL)
    await commit_job(rem_maker, escena.appointment, scheduled_for=VENCIDO)
    tick = Tick(rem_maker, settings, REMINDER_MAX_ATTEMPTS=1)
    tick.senders[W].failures.append(SendError("timeout", retryable=True))

    await tick()

    jobs = await read_jobs(rem_maker, escena.appointment.id)
    payloads = [str(e.payload) for j in jobs.values() for e in await read_events(rem_maker, j.id)]
    volcado = " ".join(
        [
            *(str(j.last_error) + str(j.reason) for j in jobs.values()),
            *payloads,
            *(
                r.getMessage()
                for r in caplog.records
                if r.name.startswith(("reminders", "app", "worker"))
            ),
        ]
    )
    assert payloads  # hay eventos que inspeccionar
    assert escena.patient.phone_e164 is not None
    for dato in (NOMBRE_PACIENTE, "Paciente", escena.patient.phone_e164, EMAIL, "/g/v1."):
        assert dato not in volcado
