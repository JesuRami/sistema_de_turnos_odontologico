"""Tabla de transiciones (C-05 D6, RN-ST-01): exhaustiva, sin DB."""

from __future__ import annotations

import itertools
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from app.common.exceptions import DomainError
from app.models import ActorType, Appointment, AppointmentStatus, UserRole
from app.modules.appointments.audit import Actor
from app.modules.appointments.states import ALLOWED, TERMINAL, Guard, check_transition

S = AppointmentStatus
BA = ZoneInfo("America/Argentina/Buenos_Aires")
INICIO = datetime(2030, 1, 7, 13, 0, tzinfo=UTC)  # lunes 10:00 BA
DESTINOS = (S.CONFIRMED, S.PRESENT, S.ABSENT, S.NO_SHOW, S.CANCELLED)
ESPERADAS = {
    (S.PENDING, S.CONFIRMED),
    (S.CONFIRMED, S.PRESENT),
    (S.CONFIRMED, S.ABSENT),
    (S.CONFIRMED, S.NO_SHOW),
    (S.PENDING, S.CANCELLED),
    (S.CONFIRMED, S.CANCELLED),
}


def _actor(*roles: UserRole) -> Actor:
    return Actor(
        clinic_id=uuid.uuid4(),
        type=ActorType.USER,
        user_id=uuid.uuid4(),
        roles=frozenset(roles or (UserRole.ADMIN,)),
    )


def _turno(status: AppointmentStatus) -> Appointment:
    return Appointment(status=status, starts_at=INICIO, ends_at=INICIO + timedelta(minutes=30))


def _ahora_valido(guard: Guard) -> datetime:
    return (
        INICIO - timedelta(hours=1) if guard is Guard.NOT_STARTED else INICIO + timedelta(hours=1)
    )


def test_la_tabla_es_exactamente_la_de_la_spec() -> None:
    assert set(ALLOWED) == ESPERADAS
    assert {S.CANCELLED, S.ABSENT, S.NO_SHOW} == TERMINAL
    assert not any(origen in TERMINAL for origen, _ in ALLOWED)


@pytest.mark.parametrize(("origen", "destino"), sorted(ESPERADAS))
def test_transiciones_permitidas(origen: AppointmentStatus, destino: AppointmentStatus) -> None:
    check_transition(
        _turno(origen), destino, _actor(), _ahora_valido(ALLOWED[(origen, destino)].guard), BA
    )


@pytest.mark.parametrize(
    ("origen", "destino"),
    sorted(set(itertools.product(list(S), DESTINOS)) - ESPERADAS),
)
def test_transiciones_prohibidas_son_409(
    origen: AppointmentStatus, destino: AppointmentStatus
) -> None:
    for ahora in (INICIO - timedelta(hours=1), INICIO + timedelta(hours=1)):
        with pytest.raises(DomainError) as exc:
            check_transition(_turno(origen), destino, _actor(), ahora, BA)
        assert (exc.value.status_code, exc.value.detail) == (409, "invalid_transition")


@pytest.mark.parametrize("destino", [S.CONFIRMED, S.CANCELLED])
def test_odontologo_no_confirma_ni_cancela(destino: AppointmentStatus) -> None:
    with pytest.raises(DomainError) as exc:
        check_transition(
            _turno(S.PENDING), destino, _actor(UserRole.ODONTOLOGO), INICIO - timedelta(hours=1), BA
        )
    assert (exc.value.status_code, exc.value.detail) == (403, "forbidden_role")


@pytest.mark.parametrize("destino", [S.PRESENT, S.ABSENT, S.NO_SHOW])
def test_odontologo_marca_asistencia(destino: AppointmentStatus) -> None:
    check_transition(
        _turno(S.CONFIRMED), destino, _actor(UserRole.ODONTOLOGO), INICIO + timedelta(hours=1), BA
    )


@pytest.mark.parametrize(
    ("origen", "destino", "ahora", "codigo"),
    [
        (S.PENDING, S.CONFIRMED, INICIO, "appointment_started"),
        (S.CONFIRMED, S.CANCELLED, INICIO + timedelta(minutes=1), "appointment_started"),
        (S.CONFIRMED, S.PRESENT, INICIO - timedelta(days=1), "attendance_too_early"),
        (S.CONFIRMED, S.ABSENT, INICIO - timedelta(minutes=1), "attendance_too_early"),
        (S.CONFIRMED, S.NO_SHOW, INICIO - timedelta(minutes=1), "attendance_too_early"),
    ],
)
def test_guardas_temporales(
    origen: AppointmentStatus, destino: AppointmentStatus, ahora: datetime, codigo: str
) -> None:
    with pytest.raises(DomainError) as exc:
        check_transition(_turno(origen), destino, _actor(), ahora, BA)
    assert (exc.value.status_code, exc.value.detail) == (409, codigo)


def test_presente_desde_el_dia_local_del_turno() -> None:
    """A las 08:00 locales del mismo día ya se puede marcar presente (turno de las 10:00)."""
    check_transition(_turno(S.CONFIRMED), S.PRESENT, _actor(), INICIO - timedelta(hours=2), BA)
