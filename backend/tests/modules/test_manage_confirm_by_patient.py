"""Confirmación del paciente compartida por el link (C-08) y WhatsApp (C-10, D7).

Postgres real (regla 9). La misma función aplica las guardas de C-08: turno iniciado → 409, ya
confirmado → no-op auditado, `pending` → `confirmed` con su evento y reconciliación.
"""

from __future__ import annotations

from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from app.common.exceptions import DomainError
from app.models import (
    ActorType,
    AppointmentEvent,
    AppointmentEventType,
    AppointmentOrigin,
    AppointmentStatus,
    CancellationReason,
)
from app.modules.manage.actions import ConfirmOutcome, confirm_by_patient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.reminder_helpers import AHORA, make_scene

pytestmark = pytest.mark.integration

TZ = ZoneInfo("America/Argentina/Buenos_Aires")


async def _eventos(session: AsyncSession, appointment_id: object) -> list[AppointmentEvent]:
    return list(
        (
            await session.execute(
                select(AppointmentEvent)
                .where(AppointmentEvent.appointment_id == appointment_id)
                .order_by(AppointmentEvent.created_at, AppointmentEvent.id)
            )
        )
        .scalars()
        .all()
    )


async def _confirmar(
    session: AsyncSession, escena: object, *, now: object = AHORA
) -> ConfirmOutcome:
    turno = escena.appointment  # type: ignore[attr-defined]
    return await confirm_by_patient(
        session,
        clinic_id=turno.clinic_id,
        appointment_id=turno.id,
        now=now,  # type: ignore[arg-type]
        tz=TZ,
        cancellation_window_hours=24,
        source="whatsapp",
    )


async def test_confirma_un_turno_pendiente(db_session: AsyncSession) -> None:
    escena = await make_scene(
        db_session, status=AppointmentStatus.PENDING, origin=AppointmentOrigin.ONLINE
    )
    antes = len(await _eventos(db_session, escena.appointment.id))

    resultado = await _confirmar(db_session, escena)

    assert resultado is ConfirmOutcome.CONFIRMED
    await db_session.refresh(escena.appointment)
    assert escena.appointment.status is AppointmentStatus.CONFIRMED
    eventos = await _eventos(db_session, escena.appointment.id)
    assert len(eventos) == antes + 1
    ultimo = eventos[-1]
    assert ultimo.event is AppointmentEventType.CONFIRMED
    assert ultimo.actor_type is ActorType.PATIENT_TOKEN
    assert ultimo.payload["source"] == "whatsapp"


async def test_ya_confirmado_es_un_noop_auditado(db_session: AsyncSession) -> None:
    escena = await make_scene(
        db_session, status=AppointmentStatus.CONFIRMED, origin=AppointmentOrigin.ONLINE
    )

    resultado = await _confirmar(db_session, escena)

    assert resultado is ConfirmOutcome.REPLAYED
    ultimo = (await _eventos(db_session, escena.appointment.id))[-1]
    assert ultimo.event is AppointmentEventType.UPDATED
    assert ultimo.payload == {"idempotent_replay": True, "action": "confirm", "source": "whatsapp"}


async def test_turno_iniciado_no_se_confirma(db_session: AsyncSession) -> None:
    escena = await make_scene(
        db_session, status=AppointmentStatus.PENDING, origin=AppointmentOrigin.ONLINE
    )

    with pytest.raises(DomainError) as exc_info:
        await _confirmar(
            db_session, escena, now=escena.appointment.starts_at + timedelta(minutes=1)
        )

    assert (exc_info.value.status_code, exc_info.value.detail) == (409, "appointment_started")


async def test_turno_cancelado_no_se_confirma(db_session: AsyncSession) -> None:
    escena = await make_scene(
        db_session, status=AppointmentStatus.PENDING, origin=AppointmentOrigin.ONLINE
    )
    turno = escena.appointment
    turno.status = AppointmentStatus.CANCELLED
    turno.cancellation_reason = CancellationReason.PACIENTE
    turno.cancelled_at = AHORA
    await db_session.flush()

    with pytest.raises(DomainError) as exc_info:
        await _confirmar(db_session, escena)

    assert exc_info.value.status_code == 409
