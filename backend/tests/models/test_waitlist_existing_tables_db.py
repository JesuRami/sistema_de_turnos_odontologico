"""Cambios de C-12 sobre tablas existentes (D1): turno `waitlist`, job de oferta, plantillas y
entrantes de WhatsApp que apuntan a una oferta. Postgres real, datos ficticios.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.models import (
    AppointmentOrigin,
    ReminderChannel,
    ReminderJob,
    ReminderStatus,
    WhatsAppInbound,
    WhatsAppIntent,
    WhatsAppOutboundReply,
    WhatsAppReplyKind,
)
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_appointment
from tests.reminder_helpers import make_template
from tests.waitlist_helpers import WaitScene, make_entry, make_offer, make_wait_scene

pytestmark = pytest.mark.integration

AHORA = datetime(2030, 1, 7, 12, 0, tzinfo=UTC)
INICIO = datetime(2030, 1, 10, 13, 0, tzinfo=UTC)


async def _falla(session: AsyncSession, objeto: object, match: str) -> None:
    with pytest.raises((IntegrityError, DBAPIError), match=match):
        async with session.begin_nested():
            session.add(objeto)
            await session.flush()


async def _offer(session: AsyncSession, s: WaitScene) -> Any:
    entry = await make_entry(session, s.clinic, s.patient)
    return await make_offer(
        session, entry, professional=s.professional, chair=s.chair, starts_at=INICIO, now=AHORA
    )


def _job(clinic_id: Any, **overrides: Any) -> ReminderJob:
    values: dict[str, Any] = {
        "clinic_id": clinic_id,
        "step": "waitlist_offer",
        "channel": ReminderChannel.WHATSAPP,
        "scheduled_for": AHORA,
        "available_at": AHORA,
        "starts_at_snapshot": INICIO,
        "status": ReminderStatus.SCHEDULED,
    }
    values.update(overrides)
    return ReminderJob(**values)


@pytest.mark.parametrize("cambios", [{"is_overbooking": True}, {"manage_token_hash": b"x" * 32}])
async def test_turno_waitlist_sin_sobreturno_ni_token(
    db_session: AsyncSession, cambios: dict[str, Any]
) -> None:
    s = await make_wait_scene(db_session)
    with pytest.raises((IntegrityError, DBAPIError), match="waitlist_plain"):
        async with db_session.begin_nested():
            extra: dict[str, Any] = (
                {"overbooking_reason": "motivo ficticio"} if "is_overbooking" in cambios else {}
            )
            await make_appointment(
                db_session,
                s.clinic,
                patient=s.patient,
                professional=s.professional,
                chair=s.chair,
                starts_at=INICIO,
                origin=AppointmentOrigin.WAITLIST,
                **cambios,
                **extra,
            )


async def test_turno_waitlist_valido(db_session: AsyncSession) -> None:
    s = await make_wait_scene(db_session)
    turno = await make_appointment(
        db_session,
        s.clinic,
        patient=s.patient,
        professional=s.professional,
        chair=s.chair,
        starts_at=INICIO,
        origin=AppointmentOrigin.WAITLIST,
    )

    assert turno.origin is AppointmentOrigin.WAITLIST


async def test_job_de_oferta_valido(db_session: AsyncSession) -> None:
    s = await make_wait_scene(db_session)
    offer = await _offer(db_session, s)
    job = _job(s.clinic.id, waitlist_offer_id=offer.id)
    db_session.add(job)
    await db_session.flush()

    assert job.appointment_id is None


async def test_job_con_turno_y_oferta_a_la_vez(db_session: AsyncSession) -> None:
    s = await make_wait_scene(db_session)
    offer = await _offer(db_session, s)
    turno = await make_appointment(
        db_session,
        s.clinic,
        patient=s.patient,
        professional=s.professional,
        chair=s.chair,
        starts_at=INICIO,
    )
    await _falla(
        db_session,
        _job(s.clinic.id, waitlist_offer_id=offer.id, appointment_id=turno.id),
        "one_target",
    )


async def test_job_sin_turno_ni_oferta(db_session: AsyncSession) -> None:
    s = await make_wait_scene(db_session)
    await _falla(db_session, _job(s.clinic.id, step="t_24h"), "one_target")


async def test_paso_de_oferta_sin_oferta(db_session: AsyncSession) -> None:
    s = await make_wait_scene(db_session)
    turno = await make_appointment(
        db_session,
        s.clinic,
        patient=s.patient,
        professional=s.professional,
        chair=s.chair,
        starts_at=INICIO,
    )
    await _falla(db_session, _job(s.clinic.id, appointment_id=turno.id), "offer_step")


async def test_oferta_con_otro_paso(db_session: AsyncSession) -> None:
    s = await make_wait_scene(db_session)
    offer = await _offer(db_session, s)
    await _falla(
        db_session, _job(s.clinic.id, waitlist_offer_id=offer.id, step="t_24h"), "offer_step"
    )


async def test_un_job_por_oferta_y_canal(db_session: AsyncSession) -> None:
    s = await make_wait_scene(db_session)
    offer = await _offer(db_session, s)
    db_session.add(_job(s.clinic.id, waitlist_offer_id=offer.id))
    await db_session.flush()

    await _falla(
        db_session, _job(s.clinic.id, waitlist_offer_id=offer.id), "uq_reminder_job_offer_channel"
    )
    email = _job(s.clinic.id, waitlist_offer_id=offer.id, channel=ReminderChannel.EMAIL)
    db_session.add(email)
    await db_session.flush()


async def test_job_de_oferta_de_otra_clinica(db_session: AsyncSession) -> None:
    a = await make_wait_scene(db_session)
    b = await make_wait_scene(db_session)
    offer_b = await _offer(db_session, b)
    await _falla(
        db_session, _job(a.clinic.id, waitlist_offer_id=offer_b.id), "fk_reminder_job_offer"
    )


async def test_plantilla_del_paso_de_oferta(db_session: AsyncSession) -> None:
    s = await make_wait_scene(db_session)
    plantilla = await make_template(
        db_session, s.clinic, ReminderChannel.WHATSAPP, "waitlist_offer"
    )

    assert plantilla.step == "waitlist_offer"


async def test_paso_invalido_sigue_rechazado(db_session: AsyncSession) -> None:
    s = await make_wait_scene(db_session)
    with pytest.raises((IntegrityError, DBAPIError), match="step_format"):
        async with db_session.begin_nested():
            await make_template(db_session, s.clinic, ReminderChannel.WHATSAPP, "oferta")


async def test_entrante_y_respuesta_con_oferta(db_session: AsyncSession) -> None:
    s = await make_wait_scene(db_session)
    offer = await _offer(db_session, s)
    inbound = WhatsAppInbound(
        clinic_id=s.clinic.id,
        provider_message_id="wamid.FICTICIO-C12-0001",
        phone_number_id="100000000000001",
        patient_id=s.patient.id,
        waitlist_offer_id=offer.id,
        intent=WhatsAppIntent.ACCEPT_OFFER,
        routed_by="context",
        occurred_at=AHORA,
    )
    db_session.add(inbound)
    await db_session.flush()
    reply = WhatsAppOutboundReply(
        clinic_id=s.clinic.id,
        inbound_id=inbound.id,
        patient_id=s.patient.id,
        waitlist_offer_id=offer.id,
        kind=WhatsAppReplyKind.OFFER_ACCEPTED,
        available_at=AHORA,
        expires_at=AHORA + timedelta(hours=24),
    )
    db_session.add(reply)
    await db_session.flush()


async def test_entrante_con_oferta_de_otra_clinica(db_session: AsyncSession) -> None:
    a = await make_wait_scene(db_session)
    b = await make_wait_scene(db_session)
    offer_b = await _offer(db_session, b)
    await _falla(
        db_session,
        WhatsAppInbound(
            clinic_id=a.clinic.id,
            provider_message_id="wamid.FICTICIO-C12-0002",
            phone_number_id="100000000000001",
            patient_id=a.patient.id,
            waitlist_offer_id=offer_b.id,
            intent=WhatsAppIntent.DECLINE_OFFER,
            routed_by="context",
            occurred_at=AHORA,
        ),
        "fk_whatsapp_inbound_offer",
    )
