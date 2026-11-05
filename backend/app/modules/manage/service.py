"""Servicio de gestión de un turno por su token (C-08).

El token NUNCA se compara ni se guarda en claro: se calcula su SHA-256 y se busca por
igualdad contra el índice único `uq_appointment_manage_token_hash` (D2). Un preimage de 256
bits no filtra información útil por tiempos, así que no hace falta `compare_digest`; no
"optimizar" a comparar el token en memoria.

Todo lo que se resuelve con un token queda acotado al `clinic_id` de su turno (regla 4).
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import DomainError
from app.core.settings import Settings
from app.models import (
    ActorType,
    Appointment,
    AppointmentEventType,
    AppointmentOrigin,
    AppointmentStatus,
    CancellationReason,
    Clinic,
    Patient,
    Professional,
)
from app.modules.appointments.audit import Actor, record_event
from app.modules.appointments.service import AppointmentsService, lock_resources
from app.modules.appointments.states import apply_transition
from app.modules.booking_public.service import (
    ALTERNATIVES,
    ALTERNATIVES_HORIZON,
    BookableProfessional,
    BookingPublicService,
    PublicClinic,
)
from app.modules.manage.reasons import REASON_OPTIONS, PatientReason
from app.modules.manage.schemas import (
    BlockedReason,
    CancelRequest,
    ManageActions,
    ManageAppointment,
    ManageAvailability,
    ManageClinic,
    ManagePolicy,
    ManageSlot,
    ManageView,
    RescheduleRequest,
)
from app.modules.reminders.invalidation import (
    NoopReminderInvalidator,
    ReminderInvalidator,
)

# `secrets.token_urlsafe(32)` de C-07: 43 caracteres url-safe, sin relleno.
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_MANAGEABLE = frozenset({AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED})
# 409 que, para el paciente, significan "ese horario ya no está" (mismo criterio que C-07).
_SLOT_LOST = frozenset({"slot_taken", "slot_blocked", "resource_inactive"})


class _SlotLostError(Exception):
    """Ningún sillón candidato quedó libre: se deshace el savepoint y se responde 409."""


@dataclass(frozen=True, slots=True)
class Link:
    """Turno resuelto por su token, con lo necesario de la clínica."""

    appointment_id: uuid.UUID
    clinic_id: uuid.UUID
    professional_id: uuid.UUID
    chair_id: uuid.UUID
    status: AppointmentStatus
    origin: AppointmentOrigin
    is_overbooking: bool
    starts_at: datetime
    ends_at: datetime
    expires_at: datetime
    patient_full_name: str
    professional_display_name: str
    clinic_name: str
    clinic_slug: str
    clinic_phone: str | None
    tz: ZoneInfo
    cancellation_window_hours: int

    @property
    def cancellation_closes_at(self) -> datetime:
        return self.starts_at - timedelta(hours=self.cancellation_window_hours)


def token_digest(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


class ManageService:
    """Casos de uso anónimos sobre el turno de un token, en un instante dado."""

    def __init__(
        self,
        session: AsyncSession,
        now: datetime,
        settings: Settings,
        invalidator: ReminderInvalidator | None = None,
    ) -> None:
        self.session = session
        self.now = now
        self.settings = settings
        self.invalidator = invalidator or NoopReminderInvalidator()
        self.ttl = timedelta(hours=settings.MANAGE_TOKEN_TTL_H)

    async def resolve(self, token: str) -> Link:
        """Formato → hash → índice único → vigencia (D4). 404 uniforme; 410 si venció."""
        if not TOKEN_RE.match(token):
            raise DomainError(404, "manage_link_not_found")
        fila = (
            await self.session.execute(
                # Columnas explícitas (regla 8); todo unido por el `clinic_id` del turno.
                select(
                    Appointment.id,
                    Appointment.clinic_id,
                    Appointment.professional_id,
                    Appointment.chair_id,
                    Appointment.status,
                    Appointment.origin,
                    Appointment.is_overbooking,
                    Appointment.starts_at,
                    Appointment.ends_at,
                    Patient.full_name,
                    Professional.display_name,
                    Clinic.name,
                    Clinic.slug,
                    Clinic.contact_phone,
                    Clinic.timezone,
                    Clinic.cancellation_window_hours,
                )
                .join(Clinic, Clinic.id == Appointment.clinic_id)
                .join(
                    Patient,
                    and_(
                        Patient.id == Appointment.patient_id,
                        Patient.clinic_id == Appointment.clinic_id,
                    ),
                )
                .join(
                    Professional,
                    and_(
                        Professional.id == Appointment.professional_id,
                        Professional.clinic_id == Appointment.clinic_id,
                    ),
                )
                .where(Appointment.manage_token_hash == token_digest(token))
            )
        ).one_or_none()
        if fila is None:
            raise DomainError(404, "manage_link_not_found")
        link = Link(
            appointment_id=fila.id,
            clinic_id=fila.clinic_id,
            professional_id=fila.professional_id,
            chair_id=fila.chair_id,
            status=fila.status,
            origin=fila.origin,
            is_overbooking=fila.is_overbooking,
            starts_at=fila.starts_at,
            ends_at=fila.ends_at,
            expires_at=fila.ends_at + self.ttl,
            patient_full_name=fila.full_name,
            professional_display_name=fila.display_name,
            clinic_name=fila.name,
            clinic_slug=fila.slug,
            clinic_phone=fila.contact_phone,
            tz=ZoneInfo(fila.timezone),
            cancellation_window_hours=fila.cancellation_window_hours,
        )
        if self.now > link.expires_at:
            # La pantalla de contacto (RN-ON-04) necesita a quién llamar; nada del paciente.
            raise DomainError(
                410,
                "manage_link_expired",
                extra={"clinic": {"name": link.clinic_name, "phone": link.clinic_phone}},
            )
        return link

    def blocked_reason(self, link: Link) -> BlockedReason | None:
        """Por qué no se puede cancelar ni reprogramar online, o `None` si se puede."""
        if link.status not in _MANAGEABLE:
            return "not_manageable"
        if self.now >= link.starts_at:
            return "past"
        if self.now > link.cancellation_closes_at:
            return "window_closed"
        return None

    def to_view(self, link: Link) -> ManageView:
        bloqueo = self.blocked_reason(link)
        return ManageView(
            clinic=ManageClinic(
                name=link.clinic_name,
                phone=link.clinic_phone,
                timezone=link.tz.key,
                slug=link.clinic_slug,
            ),
            appointment=ManageAppointment(
                # Solo el nombre de pila: si el link se reenvía, se filtra lo mínimo (D5).
                patient_first_name=link.patient_full_name.split()[0],
                starts_at=link.starts_at.astimezone(link.tz),
                ends_at=link.ends_at.astimezone(link.tz),
                professional_display_name=link.professional_display_name,
                status=link.status,
                origin=link.origin,
                is_overbooking=link.is_overbooking,
            ),
            policy=ManagePolicy(
                cancellation_window_hours=link.cancellation_window_hours,
                cancellation_closes_at=link.cancellation_closes_at.astimezone(link.tz),
            ),
            actions=ManageActions(
                # Confirmar no depende de la ventana: un turno en 3 h se puede confirmar.
                can_confirm=link.status is AppointmentStatus.PENDING and self.now < link.starts_at,
                can_cancel=bloqueo is None,
                can_reschedule=bloqueo is None,
                blocked_reason=bloqueo,
            ),
            reason_options=list(REASON_OPTIONS),
            manage_token_expires_at=link.expires_at.astimezone(link.tz),
        )

    async def view(self, token: str) -> ManageView:
        return self.to_view(await self.resolve(token))

    # -------------------------------------------------------- disponibilidad

    def _booking(self, link: Link) -> tuple[BookingPublicService, PublicClinic]:
        """La misma definición de hueco que la reserva pública (C-07), en la clínica del turno."""
        clinic = PublicClinic(id=link.clinic_id, name=link.clinic_name, tz=link.tz)
        return BookingPublicService(self.session, self.now, self.settings), clinic

    async def availability(
        self, token: str, desde: datetime, hasta: datetime
    ) -> ManageAvailability:
        """Huecos del MISMO profesional en `[desde, hasta)`; incluye el horario propio (D8)."""
        link = await self.resolve(token)
        booking, clinic = self._booking(link)
        booking.check_range(clinic, desde, hasta)
        profesional = await self._bookable(booking, clinic, link)
        if profesional is None:
            return ManageAvailability(timezone=link.tz.key, slots=[])
        slots = await booking.offerable(
            clinic, profesional, desde, hasta, exclude_appointment_id=link.appointment_id
        )
        return ManageAvailability(
            timezone=link.tz.key,
            slots=[
                ManageSlot(
                    starts_at=s.starts_at.astimezone(link.tz), ends_at=s.ends_at.astimezone(link.tz)
                )
                for s in slots
            ],
        )

    # ---------------------------------------------------------------- acciones

    async def _locked(self, link: Link) -> Appointment:
        """El turno del token con `FOR UPDATE`: dos acciones simultáneas se serializan (D9)."""
        appointment: Appointment = (
            await self.session.execute(
                select(Appointment)
                .where(
                    Appointment.id == link.appointment_id,
                    Appointment.clinic_id == link.clinic_id,
                )
                .with_for_update()
            )
        ).scalar_one()
        return appointment

    @staticmethod
    def _actor(link: Link) -> Actor:
        return Actor(clinic_id=link.clinic_id, type=ActorType.PATIENT_TOKEN)

    async def _replay(self, link: Link, appointment: Appointment, action: str) -> None:
        """Acción ya aplicada (D9): evento `updated` auditable, sin repetir la transición.

        Se reutiliza `updated` (no se agrega un valor al enum nativo) y el reporte de C-13, que
        lee la última transición, no cuenta dos veces.
        """
        await record_event(
            self.session,
            self._actor(link),
            appointment,
            AppointmentEventType.UPDATED,
            from_status=appointment.status,
            to_status=appointment.status,
            payload={"idempotent_replay": True, "action": action, "source": "manage_link"},
        )

    async def confirm(self, token: str) -> ManageView:
        """`pending → confirmed` (D6); ya confirmado no repite la transición."""
        link = await self.resolve(token)
        appointment = await self._locked(link)
        if self.now >= appointment.starts_at:
            raise DomainError(409, "appointment_started")
        if appointment.status is AppointmentStatus.CONFIRMED:
            await self._replay(link, appointment, "confirm")
        else:
            # Mutación + invalidación de recordatorios: una sola unidad (D11).
            async with self.session.begin_nested():
                await apply_transition(
                    self.session,
                    appointment,
                    AppointmentStatus.CONFIRMED,
                    self._actor(link),
                    now=self.now,
                    tz=link.tz,
                    cancellation_window_hours=link.cancellation_window_hours,
                    extra_payload={"source": "manage_link"},
                )
                await self.invalidator.invalidated(self.session, appointment, action="confirm")
        await self.session.commit()
        return await self.view(token)

    async def cancel(self, token: str, payload: CancelRequest) -> ManageView:
        """`pending|confirmed → cancelled` dentro de la ventana de la clínica (D7, RN-CX-01).

        La causa guardada es siempre `paciente` (C-13 agrupa por esos 5 valores); el motivo
        fino va en el evento como `patient_reason`. La nota libre se guarda solo con `otro`
        y nunca entra al evento, a logs ni a exportaciones.
        """
        link = await self.resolve(token)
        appointment = await self._locked(link)
        if appointment.status is AppointmentStatus.CANCELLED:
            await self._replay(link, appointment, "cancel")
        else:
            self._assert_cancellable(link, appointment)
            extra: dict[str, object] = {"source": "manage_link"}
            if payload.reason is not None:
                extra["patient_reason"] = payload.reason
            async with self.session.begin_nested():
                await apply_transition(
                    self.session,
                    appointment,
                    AppointmentStatus.CANCELLED,
                    self._actor(link),
                    now=self.now,
                    tz=link.tz,
                    cancellation_window_hours=link.cancellation_window_hours,
                    reason=CancellationReason.PACIENTE,
                    note=None,  # `apply_transition` copiaría la nota al payload del evento.
                    extra_payload=extra,
                )
                if payload.reason is PatientReason.OTRO and payload.note is not None:
                    appointment.cancellation_note = payload.note
                    await self.session.flush()
                await self.invalidator.invalidated(self.session, appointment, action="cancel")
        await self.session.commit()
        return await self.view(token)

    def _assert_cancellable(self, link: Link, appointment: Appointment) -> None:
        """Estado operable → turno no iniciado → ventana abierta; sin mutar nada."""
        if appointment.status not in _MANAGEABLE:
            raise DomainError(409, "invalid_transition")
        if self.now >= appointment.starts_at:
            # RN-CX-05: el paciente necesita otro mensaje que el `appointment_started` de la guarda.
            raise DomainError(422, "appointment_in_past")
        if self.now > appointment.starts_at - timedelta(hours=link.cancellation_window_hours):
            raise DomainError(409, "cancellation_window_closed")

    async def reschedule(self, token: str, payload: RescheduleRequest) -> ManageView:
        """Mueve el turno a un inicio ofrecible del mismo profesional, atómicamente (D8).

        Orden único de locks (C-05 D4): profesional → sillones → turno, igual que la
        reprogramación de recepción. Por eso los sillones candidatos se calculan ANTES de
        bloquear el turno: tomarlo primero cruza los locks con recepción (deadlock).
        """
        link = await self.resolve(token)
        destino = payload.starts_at
        booking, clinic = self._booking(link)
        profesional: BookableProfessional | None = None
        candidatos: list[uuid.UUID] = []
        if destino != link.starts_at and destino > self.now:
            profesional = await self._bookable(booking, clinic, link)
            if profesional is not None:
                candidatos = booking.candidates(clinic, profesional, destino)
        await lock_resources(
            self.session, link.clinic_id, [link.professional_id], [link.chair_id, *candidatos]
        )
        appointment = await self._locked(link)
        self._assert_cancellable(link, appointment)
        if appointment.starts_at == destino:
            await self._replay(link, appointment, "reschedule")
        else:
            if destino <= self.now:
                raise DomainError(422, "appointment_in_past")
            if profesional is None or not candidatos:
                raise DomainError(422, "slot_not_offered")
            try:
                async with self.session.begin_nested():
                    await self._move_first_free(link, appointment, destino, candidatos)
                    await self.invalidator.invalidated(
                        self.session, appointment, action="reschedule"
                    )
            except _SlotLostError:
                alternativos = await booking.offerable(
                    clinic,
                    profesional,
                    destino,
                    destino + ALTERNATIVES_HORIZON,
                    cap=ALTERNATIVES,
                    exclude_appointment_id=link.appointment_id,
                )
                raise DomainError(
                    409,
                    "slot_taken",
                    extra={
                        "alternatives": [
                            {
                                "starts_at": s.starts_at.astimezone(link.tz).isoformat(),
                                "ends_at": s.ends_at.astimezone(link.tz).isoformat(),
                            }
                            for s in alternativos
                        ]
                    },
                ) from None
        await self.session.commit()
        return await self.view(token)

    @staticmethod
    async def _bookable(
        booking: BookingPublicService, clinic: PublicClinic, link: Link
    ) -> BookableProfessional | None:
        """El profesional del turno si sigue reservable online; si no, no hay a dónde mover."""
        try:
            return await booking.bookable_professional(clinic, link.professional_id)
        except DomainError as error:
            if error.detail == "professional_not_found":
                return None
            raise

    async def _move_first_free(
        self,
        link: Link,
        appointment: Appointment,
        destino: datetime,
        candidatos: list[uuid.UUID],
    ) -> None:
        """Un intento por sillón candidato (orden por id; lock profesional → sillón).

        El único camino de escritura es `AppointmentsService.reschedule`, con el EXCLUDE de la
        base como barrera final (regla 1). La duración no cambia: mover no cambia la práctica.
        """
        appointments = AppointmentsService(self.session, self._actor(link), self.now)
        duracion = int((appointment.ends_at - appointment.starts_at).total_seconds() // 60)
        for chair_id in candidatos:
            try:
                await appointments.reschedule(
                    appointment.id,
                    {"starts_at": destino, "chair_id": chair_id, "duration_min": duracion},
                    event_extra={"source": "manage_link"},
                )
                return
            except DomainError as error:
                if error.status_code == 422 and error.detail == "outside_schedule":
                    # El paciente no distingue "fuera de grilla" de "fuera de horario".
                    raise DomainError(422, "slot_not_offered") from None
                if error.status_code != 409 or error.detail not in _SLOT_LOST:
                    raise
        raise _SlotLostError
