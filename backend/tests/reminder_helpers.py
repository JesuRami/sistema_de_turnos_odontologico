"""Escenarios sintéticos del motor de recordatorios (C-09): turno, plantillas y jobs persistidos.

Todo dato es ficticio (regla 13). Los jobs se insertan directo, sin pasar por el motor, para
probar cada pieza (consentimiento, programación, despacho) por separado.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.models import (
    Appointment,
    AppointmentOrigin,
    AppointmentStatus,
    Chair,
    Clinic,
    DeliveryEvent,
    NotificationTemplate,
    Patient,
    Professional,
    ReminderChannel,
    ReminderJob,
    ReminderStatus,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import (
    make_appointment,
    make_chair,
    make_clinic,
    make_patient,
    make_professional,
    unique_email,
)

AHORA = datetime(2030, 1, 7, 8, 0, tzinfo=UTC)
W = ReminderChannel.WHATSAPP
E = ReminderChannel.EMAIL


@dataclass(frozen=True, slots=True)
class Scene:
    """Un turno con su clínica, paciente, profesional y sillón."""

    clinic: Clinic
    patient: Patient
    professional: Professional
    chair: Chair
    appointment: Appointment


async def make_scene(
    session: AsyncSession,
    *,
    clinic: Clinic | None = None,
    starts_in: timedelta = timedelta(days=5),
    opt_in: bool = False,
    email: str | None = None,
    status: AppointmentStatus = AppointmentStatus.CONFIRMED,
    origin: AppointmentOrigin = AppointmentOrigin.RECEPTION,
    **clinic_overrides: Any,
) -> Scene:
    """Turno `starts_in` después de `AHORA`; con `clinic` reutiliza esa clínica."""
    clinic = clinic or await make_clinic(session, **clinic_overrides)
    patient = await make_patient(session, clinic, whatsapp_opt_in=opt_in, email=email)
    professional = await make_professional(session, clinic)
    chair = await make_chair(session, clinic)
    appointment = await make_appointment(
        session,
        clinic,
        patient=patient,
        professional=professional,
        chair=chair,
        starts_at=AHORA + starts_in,
        status=status,
        origin=origin,
    )
    return Scene(clinic, patient, professional, chair, appointment)


async def make_template(
    session: AsyncSession,
    clinic: Clinic,
    channel: ReminderChannel,
    step: str,
    *,
    active: bool = True,
    body: str = "Hola {{nombre}}, {{fecha}} {{hora}} {{link}}",
) -> NotificationTemplate:
    plantilla = NotificationTemplate(
        clinic_id=clinic.id,
        channel=channel,
        step=step,
        meta_template_name=f"{channel.value}_{step}_v1",
        body_preview=body,
        active=active,
    )
    session.add(plantilla)
    await session.flush()
    return plantilla


async def make_job(
    session: AsyncSession,
    appointment: Appointment,
    *,
    step: str = "t_24h",
    channel: ReminderChannel = W,
    status: ReminderStatus = ReminderStatus.SCHEDULED,
    scheduled_for: datetime | None = None,
    **overrides: Any,
) -> ReminderJob:
    """Job del turno; por defecto vence 24 h antes de su inicio."""
    due = scheduled_for or appointment.starts_at - timedelta(hours=24)
    values: dict[str, Any] = {
        "clinic_id": appointment.clinic_id,
        "appointment_id": appointment.id,
        "step": step,
        "channel": channel,
        "scheduled_for": due,
        "available_at": due,
        "starts_at_snapshot": appointment.starts_at,
        "status": status,
    }
    if status is ReminderStatus.SENDING:
        values.setdefault("claimed_at", due)
    if status in (ReminderStatus.SENT, ReminderStatus.DELIVERED, ReminderStatus.READ):
        values.setdefault("sent_at", due)
    values.update(overrides)
    job = ReminderJob(**values)
    session.add(job)
    await session.flush()
    return job


async def jobs_of(
    session: AsyncSession, appointment_id: uuid.UUID
) -> dict[tuple[str, str], ReminderJob]:
    """Jobs del turno por `(paso, canal)`, releídos de la base (ignora el identity map)."""
    filas = (
        (
            await session.execute(
                select(ReminderJob)
                .where(ReminderJob.appointment_id == appointment_id)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    return {(j.step, j.channel.value): j for j in filas}


async def statuses_of(session: AsyncSession, appointment_id: uuid.UUID) -> dict[str, str]:
    """`{"paso/canal": estado}` de los jobs del turno."""
    return {
        f"{paso}/{canal}": job.status.value
        for (paso, canal), job in (await jobs_of(session, appointment_id)).items()
    }


async def events_of(session: AsyncSession, job_id: uuid.UUID) -> list[DeliveryEvent]:
    return list(
        (
            await session.execute(
                select(DeliveryEvent)
                .where(DeliveryEvent.reminder_job_id == job_id)
                .order_by(DeliveryEvent.occurred_at)
            )
        )
        .scalars()
        .all()
    )


def email_ficticio() -> str:
    return unique_email("paciente.ficticio")


# ------------------------------------------------------------ despacho (commits reales)

SECRETO_LINKS = "firma-de-links-solo-para-tests-32-bytes-ok"


def dispatch_settings(settings: Any, **cambios: Any) -> Any:
    """Settings con secreto de links y proveedores `fake` (salvo que se pida otra cosa)."""
    from pydantic import SecretStr

    valores: dict[str, Any] = {
        "MANAGE_LINK_SECRET": SecretStr(SECRETO_LINKS),
        "REMINDER_WHATSAPP_PROVIDER": "fake",
        "REMINDER_EMAIL_PROVIDER": "fake",
    }
    valores.update(cambios)
    return settings.model_copy(update=valores)


async def commit_scene(
    maker: Any,
    *,
    templates: bool = True,
    **kwargs: Any,
) -> Scene:
    """Escena persistida y commiteada, con las plantillas por defecto de su clínica."""
    from app.modules.reminders.seeding import seed_default_templates

    async with maker() as session:
        escena = await make_scene(session, **kwargs)
        if templates and "clinic" not in kwargs:
            await seed_default_templates(session, escena.clinic.id)
        await session.commit()
    return escena


async def commit_job(maker: Any, appointment: Appointment, **kwargs: Any) -> ReminderJob:
    async with maker() as session:
        job = await make_job(session, appointment, **kwargs)
        await session.commit()
    return job


async def read_jobs(maker: Any, appointment_id: uuid.UUID) -> dict[tuple[str, str], ReminderJob]:
    async with maker() as session:
        return await jobs_of(session, appointment_id)


async def read_events(maker: Any, job_id: uuid.UUID) -> list[DeliveryEvent]:
    async with maker() as session:
        return await events_of(session, job_id)
