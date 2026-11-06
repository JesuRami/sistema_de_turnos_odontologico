"""Invariantes de base del canal WhatsApp (C-10, D1; reglas 4, 7, 9 y 11).

Postgres real: el formato y la unicidad del número propio, la unicidad del id de mensaje del
proveedor, la deduplicación de entrantes por clínica, el append-only de `whatsapp_inbound` y las
claves foráneas compuestas intra-tenant los impone la base, no la aplicación.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.models import (
    Appointment,
    Clinic,
    Patient,
    ReminderChannel,
    ReminderJob,
    ReminderStatus,
    WhatsAppInbound,
    WhatsAppIntent,
    WhatsAppOutboundReply,
    WhatsAppReplyKind,
    WhatsAppReplyStatus,
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


async def _tenant(session: AsyncSession) -> Tenant:
    clinic = await make_clinic(session)
    patient = await make_patient(session, clinic)
    professional = await make_professional(session, clinic)
    chair = await make_chair(session, clinic)
    appointment = await make_appointment(
        session, clinic, patient=patient, professional=professional, chair=chair, starts_at=INICIO
    )
    return Tenant(clinic, patient, appointment)


def _inbound(t: Tenant, **overrides: Any) -> WhatsAppInbound:
    values: dict[str, Any] = {
        "clinic_id": t.clinic.id,
        "provider_message_id": "wamid.FICTICIO-0001",
        "phone_number_id": "100000000000001",
        "patient_id": t.patient.id,
        "appointment_id": t.appointment.id,
        "intent": WhatsAppIntent.CONFIRM,
        "routed_by": "context",
        "occurred_at": AHORA,
    }
    values.update(overrides)
    return WhatsAppInbound(**values)


def _reply(t: Tenant, inbound: WhatsAppInbound, **overrides: Any) -> WhatsAppOutboundReply:
    values: dict[str, Any] = {
        "clinic_id": t.clinic.id,
        "inbound_id": inbound.id,
        "patient_id": t.patient.id,
        "appointment_id": t.appointment.id,
        "kind": WhatsAppReplyKind.CONFIRMED,
        "available_at": AHORA,
        "expires_at": AHORA + timedelta(hours=24),
    }
    values.update(overrides)
    return WhatsAppOutboundReply(**values)


async def _flush_falla(session: AsyncSession, *objetos: object, match: str) -> None:
    with pytest.raises((IntegrityError, DBAPIError), match=match):
        async with session.begin_nested():
            session.add_all(objetos)
            await session.flush()


# ------------------------------------------------------------------ número propio


async def test_numero_propio_valido_se_guarda(db_session: AsyncSession) -> None:
    clinic = await make_clinic(db_session)
    clinic.whatsapp_phone_number_id = "100000000000123"

    await db_session.flush()


async def test_numero_propio_con_letras_viola_el_check(db_session: AsyncSession) -> None:
    clinic = await make_clinic(db_session)

    with pytest.raises((IntegrityError, DBAPIError), match="whatsapp_phone_number_id_format"):
        async with db_session.begin_nested():
            clinic.whatsapp_phone_number_id = "abc-123"
            await db_session.flush()


async def test_un_numero_propio_es_de_una_sola_clinica(db_session: AsyncSession) -> None:
    a = await make_clinic(db_session)
    b = await make_clinic(db_session)
    a.whatsapp_phone_number_id = "100000000000777"
    await db_session.flush()

    with pytest.raises((IntegrityError, DBAPIError), match="uq_clinic_whatsapp_phone_number_id"):
        async with db_session.begin_nested():
            b.whatsapp_phone_number_id = "100000000000777"
            await db_session.flush()


async def test_varias_clinicas_pueden_usar_el_compartido(db_session: AsyncSession) -> None:
    a = await make_clinic(db_session)
    b = await make_clinic(db_session)

    assert a.whatsapp_phone_number_id is None and b.whatsapp_phone_number_id is None


# ------------------------------------------------------------------ reminder_job


async def test_id_de_mensaje_del_proveedor_es_unico(db_session: AsyncSession) -> None:
    t = await _tenant(db_session)

    def job(paso: str) -> ReminderJob:
        return ReminderJob(
            clinic_id=t.clinic.id,
            appointment_id=t.appointment.id,
            step=paso,
            channel=ReminderChannel.WHATSAPP,
            scheduled_for=AHORA,
            available_at=AHORA,
            starts_at_snapshot=INICIO,
            status=ReminderStatus.SENT,
            sent_at=AHORA,
            provider_message_id="wamid.REPETIDO",
        )

    db_session.add(job("t_72h"))
    await db_session.flush()

    await _flush_falla(db_session, job("t_24h"), match="uq_reminder_job_provider_message_id")


# ------------------------------------------------------------------ whatsapp_inbound


async def test_entrante_duplicado_en_la_misma_clinica_se_rechaza(db_session: AsyncSession) -> None:
    t = await _tenant(db_session)
    db_session.add(_inbound(t))
    await db_session.flush()

    await _flush_falla(db_session, _inbound(t), match="uq_whatsapp_inbound_clinic_id")


async def test_mismo_entrante_en_dos_clinicas_se_admite(db_session: AsyncSession) -> None:
    a = await _tenant(db_session)
    b = await _tenant(db_session)
    db_session.add_all([_inbound(a), _inbound(b)])

    await db_session.flush()


async def test_entrante_es_append_only(db_session: AsyncSession) -> None:
    t = await _tenant(db_session)
    fila = _inbound(t)
    db_session.add(fila)
    await db_session.flush()

    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(
                update(WhatsAppInbound)
                .where(WhatsAppInbound.id == fila.id)
                .values(intent=WhatsAppIntent.STOP)
            )
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(delete(WhatsAppInbound).where(WhatsAppInbound.id == fila.id))


async def test_routed_by_cerrado(db_session: AsyncSession) -> None:
    t = await _tenant(db_session)

    await _flush_falla(db_session, _inbound(t, routed_by="adivinado"), match="routed_by")


async def test_entrante_sin_paciente_ni_turno_se_admite(db_session: AsyncSession) -> None:
    t = await _tenant(db_session)
    db_session.add(_inbound(t, patient_id=None, appointment_id=None, routed_by="phone"))

    await db_session.flush()


# ------------------------------------------------------------------ whatsapp_outbound_reply


async def test_respuesta_nace_pendiente_sin_intentos(db_session: AsyncSession) -> None:
    t = await _tenant(db_session)
    entrante = _inbound(t)
    db_session.add(entrante)
    await db_session.flush()
    respuesta = _reply(t, entrante)
    db_session.add(respuesta)
    await db_session.flush()
    await db_session.refresh(respuesta)

    assert respuesta.status is WhatsAppReplyStatus.PENDING
    assert respuesta.attempts == 0


async def test_una_respuesta_por_entrante_y_tipo(db_session: AsyncSession) -> None:
    t = await _tenant(db_session)
    entrante = _inbound(t)
    db_session.add(entrante)
    await db_session.flush()
    db_session.add(_reply(t, entrante))
    await db_session.flush()

    await _flush_falla(
        db_session, _reply(t, entrante), match="uq_whatsapp_outbound_reply_inbound_id_kind"
    )


async def test_sending_exige_claimed_at(db_session: AsyncSession) -> None:
    t = await _tenant(db_session)
    entrante = _inbound(t)
    db_session.add(entrante)
    await db_session.flush()

    await _flush_falla(
        db_session,
        _reply(t, entrante, status=WhatsAppReplyStatus.SENDING),
        match="sending_has_claim",
    )


# ------------------------------------------------------ aislamiento cross-tenant (regla 4)


async def test_entrante_de_b_no_puede_apuntar_a_paciente_de_a(db_session: AsyncSession) -> None:
    a = await _tenant(db_session)
    b = await _tenant(db_session)

    await _flush_falla(
        db_session,
        _inbound(b, patient_id=a.patient.id, appointment_id=None),
        match="fk_whatsapp_inbound_clinic_id_patient_id_patient",
    )


async def test_entrante_de_b_no_puede_apuntar_a_turno_de_a(db_session: AsyncSession) -> None:
    a = await _tenant(db_session)
    b = await _tenant(db_session)

    await _flush_falla(
        db_session,
        _inbound(b, patient_id=None, appointment_id=a.appointment.id),
        match="fk_whatsapp_inbound_clinic_id_appointment_id_appointment",
    )


async def test_respuesta_de_b_no_puede_apuntar_a_entrante_de_a(db_session: AsyncSession) -> None:
    a = await _tenant(db_session)
    b = await _tenant(db_session)
    entrante = _inbound(a)
    db_session.add(entrante)
    await db_session.flush()

    await _flush_falla(
        db_session,
        _reply(b, entrante),
        match="fk_whatsapp_outbound_reply_inbound",
    )


async def test_respuesta_de_b_no_puede_apuntar_a_paciente_de_a(db_session: AsyncSession) -> None:
    a = await _tenant(db_session)
    b = await _tenant(db_session)
    entrante = _inbound(b)
    db_session.add(entrante)
    await db_session.flush()

    await _flush_falla(
        db_session,
        _reply(b, entrante, patient_id=a.patient.id, appointment_id=None),
        match="fk_whatsapp_outbound_reply_clinic_id_patient_id_patient",
    )


async def test_constraints_validados(db_session: AsyncSession) -> None:
    """Regla 11: el CHECK nació `NOT VALID` y quedó validado; los índices concurrentes, válidos."""
    check = await db_session.scalar(
        text(
            "SELECT convalidated FROM pg_constraint "
            "WHERE conname = 'ck_clinic_whatsapp_phone_number_id_format'"
        )
    )
    assert check is True
    indices = (
        await db_session.execute(
            text(
                "SELECT c.relname, i.indisvalid FROM pg_index i JOIN pg_class c "
                "ON c.oid = i.indexrelid WHERE c.relname IN "
                "('uq_clinic_whatsapp_phone_number_id', 'uq_reminder_job_provider_message_id')"
            )
        )
    ).all()
    assert sorted(indices) == [
        ("uq_clinic_whatsapp_phone_number_id", True),
        ("uq_reminder_job_provider_message_id", True),
    ]
