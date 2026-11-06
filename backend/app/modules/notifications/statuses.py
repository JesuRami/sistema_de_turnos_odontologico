"""Estados de entrega informados por Meta (C-10, D6; spec whatsapp-webhook).

- El job se encuentra por `provider_message_id` (único); un id desconocido (respuesta de sesión,
  otro sistema) se ignora.
- Cada estado se registra en `delivery_event` con `provider_event_id = "<id>:<estado>"`; la
  unicidad `(reminder_job_id, provider_event_id)` descarta los reenvíos de Meta.
- `delivered` y `read` avanzan el job en el orden `sent → delivered → read`, sin retroceder.
- `failed` de un job `sent` lo deja `failed` (`provider_rejected`, `meta_<código>`) y escala a
  email con las mismas reglas que una falla de envío; de un job ya entregado solo se registra.
- `sent` lo ignora: el motor ya registró su propio evento al enviar.

Todo filtra por el `clinic_id` del job (regla 4). Ni el payload del evento ni los logs llevan el
destinatario (regla 13): solo el código de error de Meta.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Appointment,
    ConsentStatus,
    DeliveryEvent,
    DeliveryEventType,
    Patient,
    ReminderChannel,
    ReminderJob,
    ReminderReason,
    ReminderStatus,
)
from app.modules.notifications.payload import StatusEvent
from app.modules.reminders.consent import ConsentService
from app.modules.reminders.jobs import escalate_to_email

_EVENTO = {
    "delivered": DeliveryEventType.DELIVERED,
    "read": DeliveryEventType.READ,
    "failed": DeliveryEventType.FAILED,
}
_RANGO = {ReminderStatus.SENT: 1, ReminderStatus.DELIVERED: 2, ReminderStatus.READ: 3}
_DESTINO = {"delivered": ReminderStatus.DELIVERED, "read": ReminderStatus.READ}


def meta_instant(timestamp: str) -> datetime:
    return datetime.fromtimestamp(int(timestamp), UTC)


async def apply_status(session: AsyncSession, status: StatusEvent, *, now: datetime) -> None:
    tipo = _EVENTO.get(status.status)
    if tipo is None:
        return
    job = await session.scalar(
        select(ReminderJob).where(ReminderJob.provider_message_id == status.id).with_for_update()
    )
    if job is None:
        return
    codigo = f"meta_{status.errors[0].code}" if status.errors else "meta_unknown"
    payload = {"source": "meta"} | ({"code": codigo} if tipo is DeliveryEventType.FAILED else {})
    nuevo = await session.scalar(
        pg_insert(DeliveryEvent)
        .values(
            clinic_id=job.clinic_id,
            reminder_job_id=job.id,
            event_type=tipo,
            provider_event_id=f"{status.id}:{status.status}",
            payload=payload,
            occurred_at=meta_instant(status.timestamp),
        )
        .on_conflict_do_nothing(
            index_elements=["reminder_job_id", "provider_event_id"],
            index_where=DeliveryEvent.provider_event_id.is_not(None),
        )
        .returning(DeliveryEvent.id)
    )
    if nuevo is None:
        return  # reenvío de Meta: ya aplicado
    if status.status in _DESTINO:
        destino = _DESTINO[status.status]
        if _RANGO.get(job.status, 99) < _RANGO[destino]:
            job.status = destino
        return
    if job.status is not ReminderStatus.SENT:
        return  # falla tardía de un mensaje ya entregado/leído: solo queda el evento
    job.status = ReminderStatus.FAILED
    job.reason = ReminderReason.PROVIDER_REJECTED.value
    job.last_error = codigo
    await session.flush()
    await _escalate(session, job, now=now)


async def _escalate(session: AsyncSession, job: ReminderJob, *, now: datetime) -> None:
    fila = (
        await session.execute(
            select(Appointment.starts_at, Patient.id, Patient.email)
            .join(
                Patient,
                (Patient.clinic_id == Appointment.clinic_id)
                & (Patient.id == Appointment.patient_id),
            )
            .where(Appointment.clinic_id == job.clinic_id, Appointment.id == job.appointment_id)
        )
    ).one()
    email = (fila.email or "").strip() or None
    bloqueado = (
        await ConsentService(session).current(job.clinic_id, fila.id, ReminderChannel.EMAIL)
        is ConsentStatus.OPT_OUT
    )
    await escalate_to_email(
        session,
        job,
        starts_at=fila.starts_at,
        patient_email=email,
        email_blocked=bloqueado,
        now=now,
    )
