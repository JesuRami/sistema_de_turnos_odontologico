"""Invariantes de base de las tablas del motor de recordatorios (C-09, D1; reglas 4, 7 y 9).

Postgres real: la unicidad de la secuencia, las claves foráneas compuestas intra-tenant y los
triggers append-only los impone la base, no la aplicación.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.models import (
    Appointment,
    Clinic,
    Consent,
    ConsentSource,
    ConsentStatus,
    DeliveryEvent,
    DeliveryEventType,
    NotificationTemplate,
    Patient,
    ReminderChannel,
    ReminderJob,
    ReminderStatus,
)
from sqlalchemy import delete, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import (
    make_appointment,
    make_chair,
    make_clinic,
    make_patient,
    make_professional,
)

pytestmark = pytest.mark.integration

AHORA = datetime(2030, 1, 7, 8, 0, tzinfo=UTC)
INICIO = AHORA + timedelta(days=5)


@dataclass(frozen=True, slots=True)
class Tenant:
    clinic: Clinic
    patient: Patient
    appointment: Appointment
    template: NotificationTemplate


async def _tenant(session: AsyncSession) -> Tenant:
    clinic = await make_clinic(session)
    patient = await make_patient(session, clinic)
    professional = await make_professional(session, clinic)
    chair = await make_chair(session, clinic)
    appointment = await make_appointment(
        session, clinic, patient=patient, professional=professional, chair=chair, starts_at=INICIO
    )
    template = NotificationTemplate(
        clinic_id=clinic.id,
        channel=ReminderChannel.WHATSAPP,
        step="t_24h",
        meta_template_name="recordatorio_24h_v1",
        body_preview="Hola {{nombre}}",
    )
    session.add(template)
    await session.flush()
    return Tenant(clinic, patient, appointment, template)


def _job(t: Tenant, **overrides: Any) -> ReminderJob:
    values: dict[str, Any] = {
        "clinic_id": t.clinic.id,
        "appointment_id": t.appointment.id,
        "step": "t_24h",
        "channel": ReminderChannel.WHATSAPP,
        "scheduled_for": INICIO - timedelta(hours=24),
        "available_at": INICIO - timedelta(hours=24),
        "starts_at_snapshot": INICIO,
    }
    values.update(overrides)
    return ReminderJob(**values)


async def _flush_falla(session: AsyncSession, *objetos: object, match: str) -> None:
    """Inserta en un savepoint y exige que la base lo rechace por `match`."""
    with pytest.raises((IntegrityError, DBAPIError), match=match):
        async with session.begin_nested():
            session.add_all(objetos)
            await session.flush()


async def test_un_job_valido_nace_scheduled_sin_intentos(db_session: AsyncSession) -> None:
    t = await _tenant(db_session)
    job = _job(t, template_id=t.template.id)
    db_session.add(job)
    await db_session.flush()
    await db_session.refresh(job)

    assert job.status is ReminderStatus.SCHEDULED
    assert job.attempts == 0
    assert job.sent_at is None and job.claimed_at is None


async def test_la_base_rechaza_un_segundo_job_del_mismo_turno_paso_y_canal(
    db_session: AsyncSession,
) -> None:
    t = await _tenant(db_session)
    db_session.add(_job(t))
    await db_session.flush()

    await _flush_falla(db_session, _job(t), match="uq_reminder_job_appointment_id_step_channel")


async def test_mismo_paso_en_otro_canal_es_otro_job(db_session: AsyncSession) -> None:
    t = await _tenant(db_session)
    db_session.add_all([_job(t), _job(t, channel=ReminderChannel.EMAIL)])

    await db_session.flush()


@pytest.mark.parametrize("paso", ["t_24", "T_24H", "foo", "", "t_h", "created2"])
async def test_el_formato_del_paso_se_valida_en_la_base(
    db_session: AsyncSession, paso: str
) -> None:
    t = await _tenant(db_session)

    await _flush_falla(db_session, _job(t, step=paso), match="step_format")


@pytest.mark.parametrize("paso", ["created", "t_3h", "t_72h", "t_168h"])
async def test_pasos_validos_se_aceptan(db_session: AsyncSession, paso: str) -> None:
    t = await _tenant(db_session)
    db_session.add(_job(t, step=paso))

    await db_session.flush()


async def test_intentos_negativos_violan_el_check(db_session: AsyncSession) -> None:
    t = await _tenant(db_session)

    await _flush_falla(db_session, _job(t, attempts=-1), match="attempts_nonneg")


async def test_sending_exige_claimed_at_y_sent_exige_sent_at(db_session: AsyncSession) -> None:
    t = await _tenant(db_session)

    await _flush_falla(
        db_session, _job(t, status=ReminderStatus.SENDING), match="sending_has_claim"
    )
    await _flush_falla(
        db_session, _job(t, step="t_3h", status=ReminderStatus.SENT), match="sent_has_sent_at"
    )


async def test_locale_de_la_plantilla_solo_es_ar(db_session: AsyncSession) -> None:
    clinic = await make_clinic(db_session)
    plantilla = NotificationTemplate(
        clinic_id=clinic.id,
        channel=ReminderChannel.WHATSAPP,
        step="t_3h",
        meta_template_name="recordatorio_3h_v1",
        body_preview="Hola",
        locale="en_US",
    )

    await _flush_falla(db_session, plantilla, match="locale_es_ar")


async def test_una_plantilla_por_clinica_canal_y_paso(db_session: AsyncSession) -> None:
    t = await _tenant(db_session)
    otra = NotificationTemplate(
        clinic_id=t.clinic.id,
        channel=ReminderChannel.WHATSAPP,
        step="t_24h",
        meta_template_name="otra",
        body_preview="Hola",
    )

    await _flush_falla(db_session, otra, match="uq_notification_template")


# ------------------------------------------------------ aislamiento cross-tenant (regla 4)


async def test_job_de_la_clinica_b_no_puede_apuntar_a_un_turno_de_la_a(
    db_session: AsyncSession,
) -> None:
    a = await _tenant(db_session)
    b = await _tenant(db_session)

    await _flush_falla(
        db_session,
        _job(a, clinic_id=b.clinic.id),
        match="fk_reminder_job_clinic_id_appointment_id_appointment",
    )


async def test_job_de_la_clinica_b_no_puede_usar_una_plantilla_de_la_a(
    db_session: AsyncSession,
) -> None:
    a = await _tenant(db_session)
    b = await _tenant(db_session)

    await _flush_falla(
        db_session,
        _job(b, template_id=a.template.id),
        match="fk_reminder_job_clinic_id_template_id_notification_template",
    )


async def test_consentimiento_de_la_clinica_b_no_puede_apuntar_a_un_paciente_de_la_a(
    db_session: AsyncSession,
) -> None:
    a = await _tenant(db_session)
    b = await _tenant(db_session)
    consent = Consent(
        clinic_id=b.clinic.id,
        patient_id=a.patient.id,
        channel=ReminderChannel.WHATSAPP,
        status=ConsentStatus.OPT_IN,
        source=ConsentSource.BOOKING,
    )

    await _flush_falla(db_session, consent, match="fk_consent_clinic_id_patient_id_patient")


async def test_evento_de_la_clinica_b_no_puede_apuntar_a_un_job_de_la_a(
    db_session: AsyncSession,
) -> None:
    a = await _tenant(db_session)
    b = await _tenant(db_session)
    job = _job(a)
    db_session.add(job)
    await db_session.flush()
    evento = DeliveryEvent(
        clinic_id=b.clinic.id, reminder_job_id=job.id, event_type=DeliveryEventType.SENT
    )

    await _flush_falla(
        db_session, evento, match="fk_delivery_event_clinic_id_reminder_job_id_reminder_job"
    )


async def test_consentimiento_de_recepcion_exige_usuario(db_session: AsyncSession) -> None:
    t = await _tenant(db_session)
    consent = Consent(
        clinic_id=t.clinic.id,
        patient_id=t.patient.id,
        channel=ReminderChannel.WHATSAPP,
        status=ConsentStatus.OPT_IN,
        source=ConsentSource.RECEPTION,
    )

    await _flush_falla(db_session, consent, match="reception_has_user")


# ------------------------------------------------------------ append-only (regla 7)


async def _evento(session: AsyncSession, t: Tenant, **overrides: Any) -> DeliveryEvent:
    job = _job(t)
    session.add(job)
    await session.flush()
    values: dict[str, Any] = {
        "clinic_id": t.clinic.id,
        "reminder_job_id": job.id,
        "event_type": DeliveryEventType.SENT,
    }
    values.update(overrides)
    evento = DeliveryEvent(**values)
    session.add(evento)
    await session.flush()
    return evento


async def test_delivery_event_es_append_only(db_session: AsyncSession) -> None:
    t = await _tenant(db_session)
    evento = await _evento(db_session, t)

    with pytest.raises((IntegrityError, DBAPIError), match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(
                update(DeliveryEvent)
                .where(DeliveryEvent.id == evento.id)
                .values(event_type=DeliveryEventType.FAILED)
            )
    with pytest.raises((IntegrityError, DBAPIError), match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(delete(DeliveryEvent).where(DeliveryEvent.id == evento.id))


async def test_consent_es_append_only(db_session: AsyncSession) -> None:
    t = await _tenant(db_session)
    consent = Consent(
        clinic_id=t.clinic.id,
        patient_id=t.patient.id,
        channel=ReminderChannel.WHATSAPP,
        status=ConsentStatus.OPT_IN,
        source=ConsentSource.BOOKING,
    )
    db_session.add(consent)
    await db_session.flush()

    with pytest.raises((IntegrityError, DBAPIError), match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(
                update(Consent).where(Consent.id == consent.id).values(status=ConsentStatus.OPT_OUT)
            )
    with pytest.raises((IntegrityError, DBAPIError), match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(delete(Consent).where(Consent.id == consent.id))


async def test_provider_event_id_no_se_repite_por_job_pero_admite_varios_null(
    db_session: AsyncSession,
) -> None:
    t = await _tenant(db_session)
    primero = await _evento(db_session, t, provider_event_id="evt-1")
    db_session.add_all(
        [
            DeliveryEvent(
                clinic_id=t.clinic.id,
                reminder_job_id=primero.reminder_job_id,
                event_type=DeliveryEventType.ATTEMPT_FAILED,
            ),
            DeliveryEvent(
                clinic_id=t.clinic.id,
                reminder_job_id=primero.reminder_job_id,
                event_type=DeliveryEventType.ATTEMPT_FAILED,
            ),
        ]
    )
    await db_session.flush()

    await _flush_falla(
        db_session,
        DeliveryEvent(
            clinic_id=t.clinic.id,
            reminder_job_id=primero.reminder_job_id,
            event_type=DeliveryEventType.DELIVERED,
            provider_event_id="evt-1",
        ),
        match="uq_delivery_event_job_provider_event",
    )


async def test_payload_del_evento_debe_ser_un_objeto(db_session: AsyncSession) -> None:
    t = await _tenant(db_session)
    job = _job(t)
    db_session.add(job)
    await db_session.flush()

    await _flush_falla(
        db_session,
        DeliveryEvent(
            clinic_id=t.clinic.id,
            reminder_job_id=job.id,
            event_type=DeliveryEventType.SENT,
            payload=[1, 2],
        ),
        match="payload_is_object",
    )


async def test_triggers_y_funciones_existen(db_session: AsyncSession) -> None:
    filas = (
        (
            await db_session.execute(
                text(
                    "SELECT tgname FROM pg_trigger WHERE tgname IN "
                    "('trg_delivery_event_no_mutate', 'trg_consent_no_mutate')"
                )
            )
        )
        .scalars()
        .all()
    )

    assert sorted(filas) == ["trg_consent_no_mutate", "trg_delivery_event_no_mutate"]
