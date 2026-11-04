"""Servicio de turnos con commits reales (C-05 tareas 4.4/4.5): online y carrera concurrente.

Cada test usa su DB temporal migrada (`committed_engine`): las sesiones son
independientes y confirman de verdad, como dos requests en producción.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from app.common.exceptions import DomainError
from app.models import (
    ActorType,
    Appointment,
    AppointmentEvent,
    AppointmentEventType,
    AppointmentOrigin,
    AppointmentStatus,
    UserRole,
)
from app.modules.appointments.audit import Actor
from app.modules.appointments.service import AppointmentsService, Booking
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.factories import (
    make_chair,
    make_clinic,
    make_patient,
    make_professional,
    make_schedule_rule,
    make_user,
)

pytestmark = pytest.mark.integration

BA = ZoneInfo("America/Argentina/Buenos_Aires")
AHORA = datetime(2030, 1, 7, 8, 0, tzinfo=BA)
RONDAS = 20


@dataclass(frozen=True, slots=True)
class Escenario:
    clinic_id: uuid.UUID
    patient_id: uuid.UUID
    otro_patient_id: uuid.UUID
    professional_id: uuid.UUID
    chair_id: uuid.UUID
    recepcion: Actor
    online: Actor


async def _escenario(engine: AsyncEngine) -> Escenario:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        clinic = await make_clinic(session)
        professional = await make_professional(session, clinic)
        chair = await make_chair(session, clinic)
        await make_schedule_rule(
            session, clinic, professional, chair, start_time=time(9), end_time=time(13)
        )
        user = await make_user(session, clinic, role=UserRole.RECEPCION)
        escenario = Escenario(
            clinic_id=clinic.id,
            patient_id=(await make_patient(session, clinic)).id,
            otro_patient_id=(
                await make_patient(session, clinic, full_name="Paciente Ficticio Online")
            ).id,
            professional_id=professional.id,
            chair_id=chair.id,
            recepcion=Actor(
                clinic_id=clinic.id,
                type=ActorType.USER,
                user_id=user.id,
                roles=frozenset({UserRole.RECEPCION}),
            ),
            online=Actor(clinic_id=clinic.id, type=ActorType.SYSTEM),
        )
        await session.commit()
    return escenario


def _booking(
    e: Escenario, starts_at: datetime, *, online: bool = False, **extra: object
) -> Booking:
    return Booking(
        patient_id=e.otro_patient_id if online else e.patient_id,
        professional_id=e.professional_id,
        chair_id=e.chair_id,
        starts_at=starts_at,
        duration_min=None,
        # C-07: la base exige el hash del token en todo turno online.
        manage_token_hash=hashlib.sha256(uuid.uuid4().bytes).digest() if online else None,
        **extra,  # type: ignore[arg-type]
    )


async def _reservar(
    engine: AsyncEngine, actor: Actor, data: Booking, origin: AppointmentOrigin
) -> uuid.UUID:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        appointment = await AppointmentsService(session, actor, AHORA).book(data, origin=origin)
        await session.commit()
        return appointment.id


async def test_turno_online_nace_pendiente_y_nunca_sobreturno(
    committed_engine: AsyncEngine,
) -> None:
    e = await _escenario(committed_engine)

    appointment_id = await _reservar(
        committed_engine,
        e.online,
        _booking(e, datetime(2030, 1, 7, 10, 0, tzinfo=BA), online=True),
        AppointmentOrigin.ONLINE,
    )

    async with AsyncSession(committed_engine) as session:
        turno = await session.get(Appointment, appointment_id)
        assert turno is not None
        assert turno.status == AppointmentStatus.PENDING
        assert turno.origin == AppointmentOrigin.ONLINE
        assert turno.is_overbooking is False
        assert turno.created_by_user_id is None
        evento = (
            await session.execute(
                select(AppointmentEvent).where(AppointmentEvent.appointment_id == appointment_id)
            )
        ).scalar_one()
        assert evento.event == AppointmentEventType.CREATED
        assert evento.actor_type == ActorType.SYSTEM
        assert evento.to_status == AppointmentStatus.PENDING


async def test_sobreturno_online_rechazado_por_el_servicio(committed_engine: AsyncEngine) -> None:
    e = await _escenario(committed_engine)
    with pytest.raises(DomainError) as exc:
        await _reservar(
            committed_engine,
            e.online,
            _booking(
                e,
                datetime(2030, 1, 7, 10, 0, tzinfo=BA),
                online=True,
                is_overbooking=True,
                overbooking_reason="Online ficticio",
            ),
            AppointmentOrigin.ONLINE,
        )
    assert (exc.value.status_code, exc.value.detail) == (422, "overbooking_not_allowed")


async def test_turno_online_en_el_pasado_de_hoy_es_rechazado(
    committed_engine: AsyncEngine,
) -> None:
    e = await _escenario(committed_engine)
    with pytest.raises(DomainError) as exc:
        await _reservar(
            committed_engine,
            e.online,
            _booking(e, AHORA - timedelta(minutes=30), online=True),
            AppointmentOrigin.ONLINE,
        )
    assert exc.value.detail == "appointment_in_past"


def _huecos() -> list[datetime]:
    """20 huecos distintos de la plantilla del lunes (8 por semana, 3 semanas)."""
    huecos = []
    for semana in range(3):
        dia = date(2030, 1, 7) + timedelta(days=7 * semana)
        for k in range(8):
            huecos.append(datetime.combine(dia, time(9), tzinfo=BA) + timedelta(minutes=30 * k))
    return huecos[:RONDAS]


async def test_carrera_recepcion_vs_online_por_el_mismo_hueco(
    committed_engine: AsyncEngine,
) -> None:
    """20 rondas: exactamente una reserva persiste y la otra recibe `409 slot_taken`."""
    e = await _escenario(committed_engine)

    for hueco in _huecos():
        resultados = await asyncio.gather(
            _reservar(
                committed_engine, e.recepcion, _booking(e, hueco), AppointmentOrigin.RECEPTION
            ),
            _reservar(
                committed_engine,
                e.online,
                _booking(e, hueco, online=True),
                AppointmentOrigin.ONLINE,
            ),
            return_exceptions=True,
        )
        exitos = [r for r in resultados if isinstance(r, uuid.UUID)]
        rechazos = [r for r in resultados if isinstance(r, DomainError)]
        assert len(exitos) == 1, resultados
        assert len(rechazos) == 1, resultados
        assert (rechazos[0].status_code, rechazos[0].detail) == (409, "slot_taken")
        assert rechazos[0].extra is not None
        assert rechazos[0].extra["conflicts"] == [str(exitos[0])]

    async with AsyncSession(committed_engine) as session:
        total = await session.scalar(select(func.count()).select_from(Appointment))
    assert total == RONDAS
