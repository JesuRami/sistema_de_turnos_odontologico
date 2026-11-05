"""Servicio de turnos (C-05): alta, reprogramación, transiciones, consulta y auditoría.

Único punto de escritura de `appointment` (contrato para C-07/C-08/C-09):

1. **Lock por recurso (D4)**: `SELECT … FOR UPDATE` sobre `professional` y
   luego `chair`, ordenados por id. Serializa todo lo que el EXCLUDE no cubre
   (bloqueos, sobreturnos, tope diario). El booking público usa este mismo
   servicio y, por lo tanto, el mismo lock.
2. Con el lock tomado: recursos activos → paciente → día no pasado → regla
   semanal → bloqueos → colisiones (incluye sobreturnos) → tope → escritura →
   evento, todo en una transacción.
3. El EXCLUDE de la base es la última barrera (regla dura 1): su violación
   (`23P01`) se traduce a `409 slot_taken` con conflictos y alternativos.

Los cuerpos de error llevan solo ids y horarios, nunca datos de pacientes (D9).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, NoReturn
from zoneinfo import ZoneInfo

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import DomainError
from app.common.pagination import decode_cursor, encode_cursor
from app.models import (
    VIGENT_STATUSES,
    Appointment,
    AppointmentEvent,
    AppointmentEventType,
    AppointmentOrigin,
    AppointmentStatus,
    Block,
    Chair,
    Clinic,
    Patient,
    Professional,
    ScheduleRule,
)
from app.modules.agenda.availability import RuleWindow, suggest_slots
from app.modules.appointments.audit import Actor, record_event
from app.modules.appointments.schemas import (
    AppointmentCreate,
    AppointmentEventList,
    AppointmentEventRead,
    AppointmentPage,
    AppointmentRead,
    AppointmentUpdate,
    PatientContact,
    PatientMinimal,
    TransitionRequest,
)
from app.modules.appointments.states import apply_transition
from app.modules.reminders.scheduling import reconcile, schedule_new

MAX_RANGE = timedelta(days=31)
_EXCLUDE_PREFIX = "ex_appointment_"
_RESCHEDULABLE = frozenset({AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED})


# ------------------------------------------------------------ piezas comunes


@dataclass(frozen=True, slots=True)
class ClinicPolicy:
    tz: ZoneInfo
    cancellation_window_hours: int
    max_overbookings_per_day: int


@dataclass(frozen=True, slots=True)
class Booking:
    """Datos de un turno a validar y escribir (alta o destino de una reprogramación)."""

    patient_id: uuid.UUID
    professional_id: uuid.UUID
    chair_id: uuid.UUID
    starts_at: datetime
    duration_min: int | None
    is_overbooking: bool = False
    overbooking_reason: str | None = None
    notes: str | None = None
    # C-07: SHA-256 del token de gestión (solo reserva online); el token en claro no entra acá.
    manage_token_hash: bytes | None = None


@dataclass(frozen=True, slots=True)
class Resolved:
    """Resultado de validar un `Booking` bajo lock."""

    ends_at: datetime
    occupied_until: datetime
    conflicts: list[uuid.UUID]
    over_limit: bool


async def load_policy(session: AsyncSession, clinic_id: uuid.UUID) -> ClinicPolicy:
    fila = (
        await session.execute(
            select(
                Clinic.timezone, Clinic.cancellation_window_hours, Clinic.max_overbookings_per_day
            ).where(Clinic.id == clinic_id)
        )
    ).one()
    return ClinicPolicy(ZoneInfo(fila.timezone), fila[1], fila[2])


async def lock_resources(
    session: AsyncSession,
    clinic_id: uuid.UUID,
    professional_ids: Iterable[uuid.UUID],
    chair_ids: Iterable[uuid.UUID],
) -> dict[uuid.UUID, tuple[bool, int]]:
    """Lock de fila (D4), siempre profesionales y luego sillones, cada grupo por id.

    Devuelve `{id: (active, buffer_min)}` de lo encontrado en la clínica (un sillón
    tiene buffer 0). Lo ajeno o inexistente simplemente no aparece.
    """
    encontrados: dict[uuid.UUID, tuple[bool, int]] = {}
    profesionales = sorted(set(professional_ids))
    if profesionales:
        filas = await session.execute(
            select(Professional.id, Professional.active, Professional.buffer_min)
            .where(Professional.clinic_id == clinic_id, Professional.id.in_(profesionales))
            .order_by(Professional.id)
            .with_for_update()
        )
        encontrados |= {f.id: (f.active, f.buffer_min) for f in filas}
    sillones = sorted(set(chair_ids))
    if sillones:
        filas = await session.execute(
            select(Chair.id, Chair.active)
            .where(Chair.clinic_id == clinic_id, Chair.id.in_(sillones))
            .order_by(Chair.id)
            .with_for_update()
        )
        encontrados |= {f.id: (f.active, 0) for f in filas}
    return encontrados


def _overlaps_resources(professional_id: uuid.UUID | None, chair_id: uuid.UUID | None) -> Any:
    condiciones = []
    if professional_id is not None:
        condiciones.append(Appointment.professional_id == professional_id)
    if chair_id is not None:
        condiciones.append(Appointment.chair_id == chair_id)
    return or_(*condiciones)


async def find_conflicts(
    session: AsyncSession,
    clinic_id: uuid.UUID,
    professional_id: uuid.UUID,
    chair_id: uuid.UUID,
    starts_at: datetime,
    occupied_until: datetime,
    exclude_id: uuid.UUID | None = None,
) -> list[uuid.UUID]:
    """Turnos vigentes (incluye sobreturnos) del profesional o del sillón que intersectan."""
    stmt = select(Appointment.id).where(
        Appointment.clinic_id == clinic_id,
        _overlaps_resources(professional_id, chair_id),
        Appointment.status.in_(VIGENT_STATUSES),
        Appointment.starts_at < occupied_until,
        Appointment.occupied_until > starts_at,
    )
    if exclude_id is not None:
        stmt = stmt.where(Appointment.id != exclude_id)
    return list(
        (await session.execute(stmt.order_by(Appointment.starts_at, Appointment.id))).scalars()
    )


async def find_affected_by_block(
    session: AsyncSession,
    clinic_id: uuid.UUID,
    professional_ids: Sequence[uuid.UUID],
    chair_ids: Sequence[uuid.UUID],
    starts_at: datetime,
    ends_at: datetime,
) -> list[Appointment]:
    """Turnos `pending/confirmed` de esos recursos que intersectan `[starts_at, ends_at)` (D10)."""
    condiciones = [Appointment.professional_id.in_(professional_ids)] if professional_ids else []
    if chair_ids:
        condiciones.append(Appointment.chair_id.in_(chair_ids))
    stmt = (
        select(Appointment)
        .where(
            Appointment.clinic_id == clinic_id,
            or_(*condiciones),
            Appointment.status.in_((AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED)),
            Appointment.starts_at < ends_at,
            Appointment.ends_at > starts_at,
        )
        .order_by(Appointment.starts_at, Appointment.id)
        .with_for_update()
    )
    return list((await session.execute(stmt)).scalars())


def _rule_window(rule: ScheduleRule) -> RuleWindow:
    return RuleWindow(
        weekday=rule.weekday,
        start_time=rule.start_time,
        end_time=rule.end_time,
        slot_duration_min=rule.slot_duration_min,
        valid_from=rule.valid_from,
        valid_to=rule.valid_to,
    )


# ------------------------------------------------------------------ servicio


class AppointmentsService:
    """Casos de uso de turnos de una clínica para un actor y un instante dados."""

    def __init__(self, session: AsyncSession, actor: Actor, now: datetime) -> None:
        self.session = session
        self.actor = actor
        self.now = now

    # --------------------------------------------------------------- alcance

    def _scoped(self, stmt: Select[Any]) -> Select[Any]:
        """Clínica del actor y, si es solo odontólogo, su profesional (en SQL)."""
        stmt = stmt.where(Appointment.clinic_id == self.actor.clinic_id)
        if self.actor.only_dentist:
            if self.actor.professional_id is None:
                raise DomainError(403, "forbidden_scope")
            stmt = stmt.where(Appointment.professional_id == self.actor.professional_id)
        return stmt

    async def _appointment(self, appointment_id: uuid.UUID, *, lock: bool = False) -> Appointment:
        stmt = self._scoped(select(Appointment)).where(Appointment.id == appointment_id)
        if lock:
            stmt = stmt.with_for_update()
        encontrado: Appointment | None = (await self.session.execute(stmt)).scalar_one_or_none()
        if encontrado is None:
            raise DomainError(404, "not_found")
        return encontrado

    # -------------------------------------------------------------- lectura

    def _read_stmt(self) -> Select[Any]:
        return self._scoped(
            select(
                Appointment, Patient.id, Patient.full_name, Patient.phone_e164, Patient.email
            ).join(
                Patient,
                and_(
                    Patient.id == Appointment.patient_id, Patient.clinic_id == Appointment.clinic_id
                ),
            )
        )

    def _to_read(self, fila: Any) -> AppointmentRead:
        appointment: Appointment = fila[0]
        patient: PatientContact | PatientMinimal
        if self.actor.only_dentist:
            patient = PatientMinimal(id=fila[1], full_name=fila[2])
        else:
            patient = PatientContact(
                id=fila[1], full_name=fila[2], phone_e164=fila[3], email=fila[4]
            )
        datos = {c: getattr(appointment, c) for c in AppointmentRead.model_fields if c != "patient"}
        return AppointmentRead(patient=patient, **datos)

    async def get(self, appointment_id: uuid.UUID) -> AppointmentRead:
        fila = (
            await self.session.execute(self._read_stmt().where(Appointment.id == appointment_id))
        ).one_or_none()
        if fila is None:
            raise DomainError(404, "not_found")
        return self._to_read(fila)

    async def list_range(
        self,
        desde: datetime,
        hasta: datetime,
        professional_id: uuid.UUID | None,
        chair_id: uuid.UUID | None,
        statuses: Sequence[AppointmentStatus] | None,
        cursor: str | None,
        limit: int,
    ) -> AppointmentPage:
        """Turnos que intersectan `[desde, hasta)`, por `(starts_at, id)`, con cursor (D12)."""
        if hasta <= desde or hasta - desde > MAX_RANGE:
            raise DomainError(422, "invalid_range")
        stmt = self._read_stmt().where(
            Appointment.starts_at < hasta, Appointment.occupied_until > desde
        )
        if professional_id is not None:
            stmt = stmt.where(Appointment.professional_id == professional_id)
        if chair_id is not None:
            stmt = stmt.where(Appointment.chair_id == chair_id)
        if statuses:
            stmt = stmt.where(Appointment.status.in_(statuses))
        if cursor:
            ts, ultimo = decode_cursor(cursor)
            stmt = stmt.where(
                or_(
                    Appointment.starts_at > ts,
                    and_(Appointment.starts_at == ts, Appointment.id > ultimo),
                )
            )
        filas = (
            await self.session.execute(
                stmt.order_by(Appointment.starts_at, Appointment.id).limit(limit + 1)
            )
        ).all()
        siguiente = None
        if len(filas) > limit:
            filas = filas[:limit]
            ultima: Appointment = filas[-1][0]
            siguiente = encode_cursor(ultima.starts_at, ultima.id)
        return AppointmentPage(items=[self._to_read(f) for f in filas], next_cursor=siguiente)

    async def events(self, appointment_id: uuid.UUID) -> AppointmentEventList:
        await self._appointment(appointment_id)
        stmt = (
            select(AppointmentEvent)
            .where(
                AppointmentEvent.clinic_id == self.actor.clinic_id,
                AppointmentEvent.appointment_id == appointment_id,
            )
            .order_by(AppointmentEvent.created_at, AppointmentEvent.id)
        )
        eventos = (await self.session.execute(stmt)).scalars().all()
        return AppointmentEventList(items=[AppointmentEventRead.model_validate(e) for e in eventos])

    # ----------------------------------------------------------------- alta

    async def create(self, payload: AppointmentCreate) -> AppointmentRead:
        """Alta desde recepción: nace `confirmed` (RN-ST-02)."""
        appointment = await self.book(
            Booking(**payload.model_dump()), origin=AppointmentOrigin.RECEPTION
        )
        await self.session.commit()
        return await self.get(appointment.id)

    async def book(
        self,
        data: Booking,
        *,
        origin: AppointmentOrigin,
        event_extra: dict[str, Any] | None = None,
    ) -> Appointment:
        """Valida bajo lock y escribe el turno + su evento (sin commit; C-07 lo reutiliza).

        `event_extra` se mezcla en el payload del evento `created` (C-07: canal elegido);
        nunca debe llevar datos personales ni el token.
        """
        if data.is_overbooking:
            if origin is AppointmentOrigin.ONLINE:
                raise DomainError(422, "overbooking_not_allowed")
            if not self.actor.is_front_desk:
                raise DomainError(403, "forbidden_role")
        policy = await load_policy(self.session, self.actor.clinic_id)
        recursos = await lock_resources(
            self.session, self.actor.clinic_id, [data.professional_id], [data.chair_id]
        )
        await self._assert_patient(data.patient_id)
        if origin is AppointmentOrigin.ONLINE and data.starts_at <= self.now:
            raise DomainError(422, "appointment_in_past")
        resuelto = await self._resolve(data, recursos, policy)

        status = (
            AppointmentStatus.PENDING
            if origin is AppointmentOrigin.ONLINE
            else AppointmentStatus.CONFIRMED
        )
        appointment = Appointment(
            clinic_id=self.actor.clinic_id,
            patient_id=data.patient_id,
            professional_id=data.professional_id,
            chair_id=data.chair_id,
            starts_at=data.starts_at,
            ends_at=resuelto.ends_at,
            occupied_until=resuelto.occupied_until,
            status=status,
            origin=origin,
            is_overbooking=data.is_overbooking,
            overbooking_reason=data.overbooking_reason if data.is_overbooking else None,
            notes=data.notes,
            created_by_user_id=self.actor.user_id,
            manage_token_hash=data.manage_token_hash,
        )
        await self._write(data, resuelto, policy, add=appointment)

        payload: dict[str, Any] = {
            "origin": origin,
            "patient_id": data.patient_id,
            "professional_id": data.professional_id,
            "chair_id": data.chair_id,
            "starts_at": data.starts_at,
            "ends_at": resuelto.ends_at,
            "occupied_until": resuelto.occupied_until,
            **(event_extra or {}),
        }
        evento = AppointmentEventType.CREATED
        if data.is_overbooking:
            evento = AppointmentEventType.OVERBOOKING_CREATED
            payload |= {
                "reason": data.overbooking_reason,
                "conflicts": resuelto.conflicts,
                "over_limit": resuelto.over_limit,
            }
        await record_event(
            self.session,
            self.actor,
            appointment,
            evento,
            from_status=None,
            to_status=status,
            payload=payload,
        )
        # C-09 (D3): alta + pasos futuros en la misma transacción que el turno.
        await schedule_new(self.session, appointment, now=self.now)
        return appointment

    # ------------------------------------------------------- reprogramación

    async def update(
        self, appointment_id: uuid.UUID, payload: AppointmentUpdate
    ) -> AppointmentRead:
        valores = payload.model_dump(include=payload.model_fields_set)
        actual = await self._appointment(appointment_id)
        if set(valores) & AppointmentUpdate.schedule_fields:
            await self._reschedule(actual, valores)
        elif "notes" in valores and valores["notes"] != actual.notes:
            anterior = actual.notes
            actual.notes = valores["notes"]
            await self.session.flush()
            await record_event(
                self.session,
                self.actor,
                actual,
                AppointmentEventType.UPDATED,
                from_status=actual.status,
                to_status=actual.status,
                payload={"notes": [anterior, actual.notes]},
            )
        else:
            return await self.get(appointment_id)
        await self.session.commit()
        return await self.get(appointment_id)

    async def reschedule(
        self,
        appointment_id: uuid.UUID,
        valores: dict[str, Any],
        *,
        event_extra: dict[str, Any] | None = None,
    ) -> Appointment:
        """Mueve el turno validando bajo lock, sin commit (C-08 lo reutiliza por token).

        `valores` usa los mismos campos que `AppointmentUpdate`; `event_extra` se mezcla en
        el payload del evento `rescheduled` y nunca debe llevar datos personales ni el token.
        Si nada cambia es un no-op y no escribe evento.
        """
        actual = await self._appointment(appointment_id)
        return await self._reschedule(actual, valores, event_extra=event_extra)

    async def _reschedule(
        self,
        actual: Appointment,
        valores: dict[str, Any],
        *,
        event_extra: dict[str, Any] | None = None,
    ) -> Appointment:
        origen = (actual.professional_id, actual.chair_id)
        destino_prof = valores.get("professional_id", actual.professional_id)
        destino_sillon = valores.get("chair_id", actual.chair_id)
        policy = await load_policy(self.session, self.actor.clinic_id)
        recursos = await lock_resources(
            self.session,
            self.actor.clinic_id,
            [origen[0], destino_prof],
            [origen[1], destino_sillon],
        )
        appointment = await self._appointment(actual.id, lock=True)
        if (appointment.professional_id, appointment.chair_id) != origen:
            # Otro request lo movió mientras esperábamos el lock: no se pisa su cambio.
            raise DomainError(409, "appointment_changed")
        if appointment.status not in _RESCHEDULABLE:
            raise DomainError(409, "invalid_transition")
        if self.now >= appointment.starts_at:
            raise DomainError(409, "appointment_started")

        es_sobreturno = valores.get("is_overbooking", appointment.is_overbooking)
        motivo = valores.get("overbooking_reason", appointment.overbooking_reason)
        if not es_sobreturno:
            motivo = None
        elif motivo is None:
            raise DomainError(422, "overbooking_reason_required")
        if es_sobreturno and not appointment.is_overbooking and not self.actor.is_front_desk:
            raise DomainError(403, "forbidden_role")
        duracion = valores.get(
            "duration_min",
            int((appointment.ends_at - appointment.starts_at).total_seconds() // 60),
        )
        data = Booking(
            patient_id=appointment.patient_id,
            professional_id=destino_prof,
            chair_id=destino_sillon,
            starts_at=valores.get("starts_at", appointment.starts_at),
            duration_min=duracion,
            is_overbooking=es_sobreturno,
            overbooking_reason=motivo,
            notes=valores.get("notes", appointment.notes),
        )
        resuelto = await self._resolve(data, recursos, policy, exclude_id=appointment.id)

        campos = (
            "professional_id",
            "chair_id",
            "starts_at",
            "ends_at",
            "occupied_until",
            "is_overbooking",
            "overbooking_reason",
            "notes",
        )
        antes = {c: getattr(appointment, c) for c in campos}
        nuevos = {
            "professional_id": data.professional_id,
            "chair_id": data.chair_id,
            "starts_at": data.starts_at,
            "ends_at": resuelto.ends_at,
            "occupied_until": resuelto.occupied_until,
            "is_overbooking": data.is_overbooking,
            "overbooking_reason": data.overbooking_reason,
            "notes": data.notes,
        }
        cambiados = [c for c in campos if antes[c] != nuevos[c]]
        if not cambiados:
            return appointment
        await self._write(data, resuelto, policy, update=(appointment, nuevos))
        payload: dict[str, Any] = {
            "before": {c: antes[c] for c in cambiados},
            "after": {c: nuevos[c] for c in cambiados},
            **(event_extra or {}),
        }
        if data.is_overbooking:
            payload |= {"conflicts": resuelto.conflicts, "over_limit": resuelto.over_limit}
        await record_event(
            self.session,
            self.actor,
            appointment,
            AppointmentEventType.RESCHEDULED,
            from_status=appointment.status,
            to_status=appointment.status,
            payload=payload,
        )
        # C-09 (D3): recalcula los jobs pendientes sobre el horario nuevo.
        await reconcile(self.session, appointment, now=self.now)
        return appointment

    # ---------------------------------------------------------- transiciones

    async def transition(
        self, appointment_id: uuid.UUID, payload: TransitionRequest
    ) -> AppointmentRead:
        appointment = await self._appointment(appointment_id, lock=True)
        policy = await load_policy(self.session, self.actor.clinic_id)
        await apply_transition(
            self.session,
            appointment,
            AppointmentStatus(payload.to),
            self.actor,
            now=self.now,
            tz=policy.tz,
            cancellation_window_hours=policy.cancellation_window_hours,
            reason=payload.reason,
            note=payload.note,
        )
        await self.session.commit()
        return await self.get(appointment_id)

    # ------------------------------------------------------- validación (D5)

    async def _assert_patient(self, patient_id: uuid.UUID) -> None:
        # `FOR SHARE` (C-06): espera a una fusión en curso (`FOR UPDATE`) y luego relee;
        # sin el lock, MVCC dejaría pasar un turno colgado del duplicado ya fusionado.
        existe = await self.session.scalar(
            select(Patient.id)
            .where(
                Patient.id == patient_id,
                Patient.clinic_id == self.actor.clinic_id,
                Patient.archived_at.is_(None),
            )
            .with_for_update(read=True)
        )
        if existe is None:
            raise DomainError(422, "invalid_patient")

    async def _resolve(
        self,
        data: Booking,
        recursos: dict[uuid.UUID, tuple[bool, int]],
        policy: ClinicPolicy,
        exclude_id: uuid.UUID | None = None,
    ) -> Resolved:
        for recurso_id in (data.professional_id, data.chair_id):
            if recurso_id not in recursos:
                raise DomainError(422, "invalid_resource")
        for recurso_id in (data.professional_id, data.chair_id):
            if not recursos[recurso_id][0]:
                raise DomainError(409, "resource_inactive")
        buffer = timedelta(minutes=recursos[data.professional_id][1])

        local = data.starts_at.astimezone(policy.tz)
        if local.date() < self.now.astimezone(policy.tz).date():
            raise DomainError(422, "appointment_in_past")
        reglas = await self._rules(data.professional_id, data.chair_id)
        regla = next(
            (
                r
                for r in reglas
                if r.applies_to(local.date()) and r.start_time <= local.time() < r.end_time
            ),
            None,
        )
        if regla is None:
            raise DomainError(422, "outside_schedule")
        duracion = timedelta(minutes=data.duration_min or regla.slot_duration_min)
        ends_at = data.starts_at + duracion
        fin_local = ends_at.astimezone(policy.tz)
        if fin_local.date() != local.date() or fin_local.time() > regla.end_time:
            raise DomainError(422, "outside_schedule")
        occupied_until = ends_at + buffer

        bloqueos = await self._blocks(data, data.starts_at, ends_at)
        if bloqueos:
            raise DomainError(409, "slot_blocked", extra={"blocks": [str(b[0]) for b in bloqueos]})

        conflictos = await find_conflicts(
            self.session,
            self.actor.clinic_id,
            data.professional_id,
            data.chair_id,
            data.starts_at,
            occupied_until,
            exclude_id,
        )
        over_limit = False
        if not data.is_overbooking:
            if conflictos:
                await self._raise_slot_taken(data, duracion, buffer, policy, conflictos, exclude_id)
        else:
            if not conflictos:
                raise DomainError(422, "overbooking_not_needed")
            over_limit = await self._overbooking_over_limit(data, policy, exclude_id)
        return Resolved(ends_at, occupied_until, conflictos, over_limit)

    async def _rules(self, professional_id: uuid.UUID, chair_id: uuid.UUID) -> list[RuleWindow]:
        filas = (
            await self.session.execute(
                select(ScheduleRule).where(
                    ScheduleRule.clinic_id == self.actor.clinic_id,
                    ScheduleRule.professional_id == professional_id,
                    ScheduleRule.chair_id == chair_id,
                    ScheduleRule.active.is_(True),
                )
            )
        ).scalars()
        return [_rule_window(r) for r in filas]

    async def _blocks(
        self, data: Booking, desde: datetime, hasta: datetime
    ) -> list[tuple[uuid.UUID, datetime, datetime]]:
        filas = await self.session.execute(
            select(Block.id, Block.starts_at, Block.ends_at)
            .where(
                Block.clinic_id == self.actor.clinic_id,
                Block.removed_at.is_(None),
                or_(Block.professional_id == data.professional_id, Block.chair_id == data.chair_id),
                Block.starts_at < hasta,
                Block.ends_at > desde,
            )
            .order_by(Block.starts_at, Block.id)
        )
        return [(f.id, f.starts_at, f.ends_at) for f in filas]

    async def _overbooking_over_limit(
        self, data: Booking, policy: ClinicPolicy, exclude_id: uuid.UUID | None
    ) -> bool:
        """RN-SB-03: tope de sobreturnos vigentes por profesional y día local."""
        dia = data.starts_at.astimezone(policy.tz).date()
        inicio_dia = datetime.combine(dia, datetime.min.time(), tzinfo=policy.tz)
        stmt = select(func.count()).where(
            Appointment.clinic_id == self.actor.clinic_id,
            Appointment.professional_id == data.professional_id,
            Appointment.is_overbooking.is_(True),
            Appointment.status.in_(VIGENT_STATUSES),
            Appointment.starts_at >= inicio_dia,
            Appointment.starts_at < inicio_dia + timedelta(days=1),
        )
        if exclude_id is not None:
            stmt = stmt.where(Appointment.id != exclude_id)
        existentes = int(await self.session.scalar(stmt) or 0)
        if existentes < policy.max_overbookings_per_day:
            return False
        if not self.actor.is_admin:
            raise DomainError(409, "overbooking_limit")
        return True

    async def _raise_slot_taken(
        self,
        data: Booking,
        duracion: timedelta,
        buffer: timedelta,
        policy: ClinicPolicy,
        conflictos: Sequence[uuid.UUID],
        exclude_id: uuid.UUID | None,
    ) -> NoReturn:
        alternativos = await self._alternatives(data, duracion, buffer, policy, exclude_id)
        raise DomainError(
            409,
            "slot_taken",
            extra={"conflicts": [str(c) for c in conflictos], "alternatives": alternativos},
        )

    async def _alternatives(
        self,
        data: Booking,
        duracion: timedelta,
        buffer: timedelta,
        policy: ClinicPolicy,
        exclude_id: uuid.UUID | None,
    ) -> list[dict[str, str]]:
        """Hasta 3 horarios libres del mismo par en 14 días (D8): solo horarios e ids."""
        hasta = data.starts_at + timedelta(days=15)
        ocupados_stmt = select(Appointment.starts_at, Appointment.occupied_until).where(
            Appointment.clinic_id == self.actor.clinic_id,
            _overlaps_resources(data.professional_id, data.chair_id),
            Appointment.status.in_(VIGENT_STATUSES),
            Appointment.starts_at < hasta,
            Appointment.occupied_until > data.starts_at,
        )
        if exclude_id is not None:
            ocupados_stmt = ocupados_stmt.where(Appointment.id != exclude_id)
        ocupados = [(f[0], f[1]) for f in await self.session.execute(ocupados_stmt)]
        bloqueos = [(b[1], b[2]) for b in await self._blocks(data, data.starts_at, hasta)]
        slots = suggest_slots(
            await self._rules(data.professional_id, data.chair_id),
            blocks=bloqueos,
            busy=ocupados,
            desde=data.starts_at,
            tz=policy.tz,
            duration=duracion,
            buffer=buffer,
            now=self.now,
        )
        return [
            {
                "starts_at": s.starts_at.isoformat(),
                "ends_at": s.ends_at.isoformat(),
                "professional_id": str(data.professional_id),
                "chair_id": str(data.chair_id),
            }
            for s in slots
        ]

    # ------------------------------------------------------------- escritura

    async def _write(
        self,
        data: Booking,
        resuelto: Resolved,
        policy: ClinicPolicy,
        *,
        add: Appointment | None = None,
        update: tuple[Appointment, dict[str, Any]] | None = None,
    ) -> None:
        """Flush en savepoint; la violación del EXCLUDE se traduce a `409 slot_taken`."""
        # El id se toma antes: si el savepoint revierte, el turno queda expirado y leerlo
        # dispararía un lazy-load sincrónico (MissingGreenlet en async).
        excluir = update[0].id if update is not None else None
        try:
            async with self.session.begin_nested():
                if add is not None:
                    self.session.add(add)
                if update is not None:
                    for campo, valor in update[1].items():
                        setattr(update[0], campo, valor)
                await self.session.flush()
        except IntegrityError as exc:
            if _EXCLUDE_PREFIX not in str(exc.orig):
                raise DomainError(422, "invalid_appointment") from None
            if update is not None:
                await self.session.refresh(update[0])
            conflictos = await find_conflicts(
                self.session,
                self.actor.clinic_id,
                data.professional_id,
                data.chair_id,
                data.starts_at,
                resuelto.occupied_until,
                excluir,
            )
            duracion = resuelto.ends_at - data.starts_at
            buffer = resuelto.occupied_until - resuelto.ends_at
            await self._raise_slot_taken(data, duracion, buffer, policy, conflictos, excluir)
        if add is not None:
            await self.session.refresh(add)
