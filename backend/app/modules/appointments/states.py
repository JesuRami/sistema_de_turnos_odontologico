"""Máquina de estados del turno (C-05 D6, RN-ST-01..04, RN-CX-02..05).

`ALLOWED` es la única fuente de verdad de las transiciones. Toda transición
pasa por `apply_transition`, que valida rol, par permitido y guarda temporal,
muta el turno y escribe su evento en la misma transacción (sin commit propio).

- `absent`: no vino pero avisó (tarde o con justificación).
- `no_show`: no vino y no avisó.
- `cancelled`, `absent` y `no_show` son terminales y liberan el hueco.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import DomainError
from app.models import (
    ActorType,
    Appointment,
    AppointmentEventType,
    AppointmentStatus,
    CancellationReason,
    UserRole,
)
from app.modules.appointments.audit import Actor, record_event
from app.modules.reminders.scheduling import reconcile

S = AppointmentStatus
_FRONT_DESK = frozenset({UserRole.ADMIN, UserRole.RECEPCION})
_STAFF = frozenset({UserRole.ADMIN, UserRole.RECEPCION, UserRole.ODONTOLOGO})


class Guard(enum.Enum):
    """Condición temporal de una transición."""

    NOT_STARTED = "not_started"  # now < starts_at
    FROM_APPOINTMENT_DAY = "from_appointment_day"  # día local de hoy >= día del turno
    FROM_START = "from_start"  # now >= starts_at


@dataclass(frozen=True, slots=True)
class Rule:
    roles: frozenset[UserRole]
    guard: Guard


ALLOWED: dict[tuple[AppointmentStatus, AppointmentStatus], Rule] = {
    (S.PENDING, S.CONFIRMED): Rule(_FRONT_DESK, Guard.NOT_STARTED),
    (S.CONFIRMED, S.PRESENT): Rule(_STAFF, Guard.FROM_APPOINTMENT_DAY),
    (S.CONFIRMED, S.ABSENT): Rule(_STAFF, Guard.FROM_START),
    (S.CONFIRMED, S.NO_SHOW): Rule(_STAFF, Guard.FROM_START),
    (S.PENDING, S.CANCELLED): Rule(_FRONT_DESK, Guard.NOT_STARTED),
    (S.CONFIRMED, S.CANCELLED): Rule(_FRONT_DESK, Guard.NOT_STARTED),
}

# Roles que pueden pedir cada destino (se chequea antes que el par: `403` > `409`).
TARGET_ROLES: dict[AppointmentStatus, frozenset[UserRole]] = {}
for (_, _destino), _regla in ALLOWED.items():
    TARGET_ROLES[_destino] = TARGET_ROLES.get(_destino, frozenset()) | _regla.roles

TERMINAL = frozenset({S.CANCELLED, S.ABSENT, S.NO_SHOW})
# C-08: el paciente con su token solo confirma o cancela; la asistencia es del personal.
PATIENT_TARGETS = frozenset({S.CONFIRMED, S.CANCELLED})


def _check_guard(
    guard: Guard, appointment: Appointment, target: AppointmentStatus, now: datetime, tz: ZoneInfo
) -> None:
    if guard is Guard.NOT_STARTED and now >= appointment.starts_at:
        raise DomainError(409, "appointment_started")
    if guard is Guard.FROM_START and now < appointment.starts_at:
        raise DomainError(409, "attendance_too_early")
    if guard is Guard.FROM_APPOINTMENT_DAY and (
        now.astimezone(tz).date() < appointment.starts_at.astimezone(tz).date()
    ):
        raise DomainError(409, "attendance_too_early")
    _ = target


def check_transition(
    appointment: Appointment,
    target: AppointmentStatus,
    actor: Actor,
    now: datetime,
    tz: ZoneInfo,
) -> None:
    """Valida rol → par permitido → guarda temporal, sin mutar nada."""
    if actor.type is ActorType.PATIENT_TOKEN and target not in PATIENT_TARGETS:
        # Sin roles no aplica el chequeo de rol: el destino se acota por tipo de actor.
        raise DomainError(409, "invalid_transition")
    if actor.roles and not (actor.roles & TARGET_ROLES.get(target, frozenset())):
        raise DomainError(403, "forbidden_role")
    regla = ALLOWED.get((appointment.status, target))
    if regla is None:
        raise DomainError(409, "invalid_transition")
    if actor.roles and not (actor.roles & regla.roles):
        raise DomainError(403, "forbidden_role")
    _check_guard(regla.guard, appointment, target, now, tz)


async def apply_transition(
    session: AsyncSession,
    appointment: Appointment,
    target: AppointmentStatus,
    actor: Actor,
    *,
    now: datetime,
    tz: ZoneInfo,
    cancellation_window_hours: int,
    reason: CancellationReason | None = None,
    note: str | None = None,
    extra_payload: dict[str, object] | None = None,
) -> None:
    """Aplica la transición y escribe su evento (misma transacción, sin commit)."""
    check_transition(appointment, target, actor, now, tz)
    anterior = appointment.status
    payload: dict[str, object] = dict(extra_payload or {})
    if target is S.CANCELLED:
        if reason is None:
            raise DomainError(422, "cancellation_reason_required")
        appointment.cancelled_at = now
        appointment.cancellation_reason = reason
        appointment.cancellation_note = note
        # RN-CX-01: tardía si faltan menos horas que la ventana de la clínica.
        tardia = appointment.starts_at - now < timedelta(hours=cancellation_window_hours)
        payload |= {"reason": reason, "late": tardia}
        if note is not None:
            payload["note"] = note
    appointment.status = target
    await session.flush()
    await record_event(
        session,
        actor,
        appointment,
        AppointmentEventType(target.value),
        from_status=anterior,
        to_status=target,
        payload=payload,
    )
    # C-09 (D3): cancelar, confirmar o registrar asistencia ajusta los jobs en esta transacción.
    await reconcile(session, appointment, now=now)
    if target is S.CANCELLED:
        # C-12 (D3, RN-CX-03): el hueco liberado se ofrece a la lista de espera en esta misma
        # transacción; si la evaluación falla, la cancelación revierte. Import diferido: la lista
        # de espera depende de este módulo para aceptar ofertas.
        from app.core.settings import get_settings
        from app.modules.waiting_list.engine import evaluate_cancelled

        await evaluate_cancelled(session, appointment, now=now, settings=get_settings())
