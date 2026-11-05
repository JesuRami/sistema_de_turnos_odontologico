"""Servicio de la reserva pública (C-07): lecturas anónimas y reserva sin cuenta.

Todo se resuelve bajo UN `clinic_id` obtenido del slug (regla 4). Un slug inexistente y uno
deshabilitado son indistinguibles (`404 booking_not_found`); un profesional ajeno, inactivo,
deshabilitado o sin regla vigente también (`404 professional_not_found`). Nada de lo que sale
de aquí permite reconstruir quién atiende a quién (RN-ON-01).
"""

from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import DomainError
from app.common.phone import InvalidPhoneError, normalize_phone_e164
from app.core.settings import Settings
from app.models import (
    VIGENT_STATUSES,
    ActorType,
    Appointment,
    AppointmentOrigin,
    Block,
    Chair,
    Clinic,
    ConsentSource,
    ConsentStatus,
    Patient,
    Professional,
    ReminderChannel,
    ScheduleRule,
)
from app.modules.agenda.availability import RuleWindow
from app.modules.appointments.audit import Actor
from app.modules.appointments.service import AppointmentsService, Booking
from app.modules.booking_public.availability import (
    DEFAULT_CAP,
    ChairRules,
    PublicSlot,
    Scoped,
    chairs_on_grid,
    public_slots,
)
from app.modules.booking_public.schemas import (
    AlternativeSlot,
    AvailabilityRead,
    BookingCreate,
    BookingCreated,
    CatalogRead,
    PatientInput,
    ProfessionalPublic,
    SlotRead,
)
from app.modules.clinic.service import create_patient
from app.modules.reminders.consent import ConsentService

MAX_RANGE = timedelta(days=14)
ALTERNATIVES = 3
ALTERNATIVES_HORIZON = timedelta(days=14)
EMAIL_MAX = 254
# Mismo criterio de email que el alta de pacientes de recepción (C-05).
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# 409 de `book()` que, para el paciente, significan lo mismo: "ese horario ya no está".
_SLOT_LOST = frozenset({"slot_taken", "slot_blocked", "resource_inactive"})
Channel = Literal["whatsapp", "email"]
_CUSHION = timedelta(days=1)  # holgura para el buffer y la duración de un candidato al borde


@dataclass(frozen=True, slots=True)
class PublicClinic:
    id: uuid.UUID
    name: str
    tz: ZoneInfo


@dataclass(frozen=True, slots=True)
class Contact:
    """Contacto ya validado según la tabla de D5."""

    phone_e164: str | None
    email: str | None
    channel: Channel
    opt_in_granted: bool
    warnings: tuple[str, ...]


class _SlotLostError(Exception):
    """Ningún sillón candidato quedó libre: se deshace el savepoint y se responde 409."""


@dataclass(frozen=True, slots=True)
class BookableProfessional:
    id: uuid.UUID
    display_name: str
    buffer: timedelta
    chairs: tuple[ChairRules, ...]


def _rule_window(rule: ScheduleRule) -> RuleWindow:
    return RuleWindow(
        weekday=rule.weekday,
        start_time=rule.start_time,
        end_time=rule.end_time,
        slot_duration_min=rule.slot_duration_min,
        valid_from=rule.valid_from,
        valid_to=rule.valid_to,
    )


class BookingPublicService:
    """Casos de uso anónimos de una clínica identificada por slug."""

    def __init__(self, session: AsyncSession, now: datetime, settings: Settings) -> None:
        self.session = session
        self.now = now
        self.settings = settings
        self.horizon_days = settings.PUBLIC_BOOKING_HORIZON_DAYS

    # ------------------------------------------------------------- resolución

    async def resolve_clinic(self, slug: str) -> PublicClinic:
        fila = (
            await self.session.execute(
                select(Clinic.id, Clinic.name, Clinic.timezone).where(
                    Clinic.slug == slug, Clinic.booking_enabled.is_(True)
                )
            )
        ).one_or_none()
        if fila is None:
            raise DomainError(404, "booking_not_found")
        return PublicClinic(id=fila.id, name=fila.name, tz=ZoneInfo(fila.timezone))

    async def _rules(
        self, clinic: PublicClinic, professional_ids: list[uuid.UUID] | None
    ) -> list[tuple[uuid.UUID, ScheduleRule]]:
        """Reglas activas no vencidas sobre sillones activos (opcionalmente de un profesional)."""
        hoy = self.now.astimezone(clinic.tz).date()
        stmt = (
            select(ScheduleRule.professional_id, ScheduleRule)
            .join(
                Chair,
                (Chair.id == ScheduleRule.chair_id) & (Chair.clinic_id == ScheduleRule.clinic_id),
            )
            .where(
                ScheduleRule.clinic_id == clinic.id,
                ScheduleRule.active.is_(True),
                Chair.active.is_(True),
                or_(ScheduleRule.valid_to.is_(None), ScheduleRule.valid_to >= hoy),
            )
        )
        if professional_ids is not None:
            stmt = stmt.where(ScheduleRule.professional_id.in_(professional_ids))
        return [(f[0], f[1]) for f in await self.session.execute(stmt)]

    # --------------------------------------------------------------- catálogo

    async def catalog(self, clinic: PublicClinic) -> CatalogRead:
        reglas = await self._rules(clinic, None)
        con_regla = {profesional for profesional, _ in reglas}
        filas = await self.session.execute(
            select(Professional.id, Professional.display_name)
            .where(
                Professional.clinic_id == clinic.id,
                Professional.active.is_(True),
                Professional.booking_enabled.is_(True),
                Professional.id.in_(con_regla),
            )
            .order_by(Professional.display_name, Professional.id)
        )
        return CatalogRead(
            name=clinic.name,
            timezone=clinic.tz.key,
            professionals=[ProfessionalPublic(id=f.id, display_name=f.display_name) for f in filas],
        )

    async def bookable_professional(
        self, clinic: PublicClinic, professional_id: uuid.UUID
    ) -> BookableProfessional:
        fila = (
            await self.session.execute(
                select(Professional.id, Professional.display_name, Professional.buffer_min).where(
                    Professional.clinic_id == clinic.id,
                    Professional.id == professional_id,
                    Professional.active.is_(True),
                    Professional.booking_enabled.is_(True),
                )
            )
        ).one_or_none()
        reglas = await self._rules(clinic, [professional_id]) if fila is not None else []
        if fila is None or not reglas:
            raise DomainError(404, "professional_not_found")
        por_sillon: dict[uuid.UUID, list[RuleWindow]] = {}
        for _, regla in reglas:
            por_sillon.setdefault(regla.chair_id, []).append(_rule_window(regla))
        return BookableProfessional(
            id=fila.id,
            display_name=fila.display_name,
            buffer=timedelta(minutes=fila.buffer_min),
            chairs=tuple(
                ChairRules(chair_id=chair_id, rules=tuple(ventanas))
                for chair_id, ventanas in sorted(por_sillon.items())
            ),
        )

    # ------------------------------------------------------- disponibilidad

    def check_range(self, clinic: PublicClinic, desde: datetime, hasta: datetime) -> None:
        """`hasta > desde`, ≤ 14 días y dentro del horizonte de reserva; si no, `422`."""
        hoy = self.now.astimezone(clinic.tz).date()
        limite = datetime.combine(
            hoy + timedelta(days=self.horizon_days + 1), datetime.min.time(), tzinfo=clinic.tz
        )
        if hasta <= desde or hasta - desde > MAX_RANGE or hasta > limite:
            raise DomainError(422, "invalid_range")

    async def availability(
        self,
        clinic: PublicClinic,
        professional_id: uuid.UUID,
        desde: datetime,
        hasta: datetime,
    ) -> AvailabilityRead:
        self.check_range(clinic, desde, hasta)
        profesional = await self.bookable_professional(clinic, professional_id)
        slots = await self.offerable(clinic, profesional, desde, hasta)
        return AvailabilityRead(
            timezone=clinic.tz.key,
            slots=[
                SlotRead(starts_at=s.starts_at, ends_at=s.ends_at, professional_id=professional_id)
                for s in slots
            ],
        )

    async def offerable(
        self,
        clinic: PublicClinic,
        profesional: BookableProfessional,
        desde: datetime,
        hasta: datetime,
        cap: int = DEFAULT_CAP,
        exclude_appointment_id: uuid.UUID | None = None,
    ) -> list[PublicSlot]:
        """Huecos ofrecibles de `[desde, hasta)`: la única definición, también para el 409.

        `exclude_appointment_id` (C-08) saca de los ocupados al turno que se reprograma, así
        su propio horario sigue ofreciéndose.
        """
        sillones = [c.chair_id for c in profesional.chairs]
        bloqueos = await self._blocks(clinic, profesional.id, sillones, desde, hasta)
        ocupados = await self._busy(
            clinic, profesional.id, sillones, desde, hasta, exclude_appointment_id
        )
        return public_slots(
            profesional.chairs,
            blocks=bloqueos,
            busy=ocupados,
            desde=desde,
            hasta=hasta,
            tz=clinic.tz,
            buffer=profesional.buffer,
            now=self.now,
            cap=cap,
        )

    async def _blocks(
        self,
        clinic: PublicClinic,
        professional_id: uuid.UUID,
        chair_ids: list[uuid.UUID],
        desde: datetime,
        hasta: datetime,
    ) -> list[Scoped]:
        filas = await self.session.execute(
            select(Block.professional_id, Block.chair_id, Block.starts_at, Block.ends_at).where(
                Block.clinic_id == clinic.id,
                Block.removed_at.is_(None),
                or_(Block.professional_id == professional_id, Block.chair_id.in_(chair_ids)),
                Block.starts_at < hasta + _CUSHION,
                Block.ends_at > desde,
            )
        )
        return [
            Scoped(
                None if f.professional_id == professional_id else f.chair_id,
                f.starts_at,
                f.ends_at,
            )
            for f in filas
        ]

    async def _busy(
        self,
        clinic: PublicClinic,
        professional_id: uuid.UUID,
        chair_ids: list[uuid.UUID],
        desde: datetime,
        hasta: datetime,
        exclude_appointment_id: uuid.UUID | None = None,
    ) -> list[Scoped]:
        stmt = select(
            Appointment.professional_id,
            Appointment.chair_id,
            Appointment.starts_at,
            Appointment.occupied_until,
        ).where(
            Appointment.clinic_id == clinic.id,
            or_(
                Appointment.professional_id == professional_id,
                Appointment.chair_id.in_(chair_ids),
            ),
            Appointment.status.in_(VIGENT_STATUSES),
            Appointment.starts_at < hasta + _CUSHION,
            Appointment.occupied_until > desde,
        )
        if exclude_appointment_id is not None:
            stmt = stmt.where(Appointment.id != exclude_appointment_id)
        filas = await self.session.execute(stmt)
        return [
            Scoped(
                None if f.professional_id == professional_id else f.chair_id,
                f.starts_at,
                f.occupied_until,
            )
            for f in filas
        ]

    # ----------------------------------------------------------------- reserva

    async def book(self, clinic: PublicClinic, payload: BookingCreate) -> BookingCreated:
        """Reserva anónima: valida, empareja al paciente y escribe vía `AppointmentsService`.

        Una sola transacción: ante `409` o cualquier error se deshace todo, incluido el
        paciente nuevo (savepoint). El único camino de escritura del turno es
        `AppointmentsService.book(origin=ONLINE)`.
        """
        profesional = await self.bookable_professional(clinic, payload.professional_id)
        contacto = self._contact(payload.patient)
        starts_at = payload.starts_at
        if starts_at <= self.now:
            raise DomainError(422, "appointment_in_past")
        candidatos = self.candidates(clinic, profesional, starts_at)
        if not candidatos:
            raise DomainError(422, "slot_not_offered")

        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).digest()
        actor = Actor(clinic_id=clinic.id, type=ActorType.PATIENT_TOKEN)
        appointments = AppointmentsService(self.session, actor, self.now)
        try:
            async with self.session.begin_nested():
                patient = await self._match_or_create(clinic, payload.patient, contacto)
                appointment = await self._book_first_free(
                    appointments,
                    Booking(
                        patient_id=patient.id,
                        professional_id=profesional.id,
                        chair_id=candidatos[0],
                        starts_at=starts_at,
                        duration_min=None,
                        manage_token_hash=token_hash,
                    ),
                    candidatos,
                    {
                        "channel": contacto.channel,
                        "whatsapp_opt_in_granted": contacto.opt_in_granted,
                    },
                )
        except _SlotLostError:
            raise DomainError(
                409,
                "slot_taken",
                extra={"alternatives": await self._alternatives(clinic, profesional, starts_at)},
            ) from None
        await self.session.commit()
        base = self.settings.FRONTEND_PUBLIC_URL.rstrip("/")
        return BookingCreated(
            starts_at=appointment.starts_at,
            ends_at=appointment.ends_at,
            professional_id=profesional.id,
            channel=contacto.channel,
            warnings=list(contacto.warnings),  # type: ignore[arg-type]
            manage_url=f"{base}/g/{token}",
        )

    def candidates(
        self, clinic: PublicClinic, profesional: BookableProfessional, starts_at: datetime
    ) -> list[uuid.UUID]:
        """Sillones cuya grilla vigente genera `starts_at`, dentro del horizonte, por id."""
        hoy = self.now.astimezone(clinic.tz).date()
        limite = datetime.combine(
            hoy + timedelta(days=self.horizon_days + 1), datetime.min.time(), tzinfo=clinic.tz
        )
        if starts_at >= limite:
            return []
        return chairs_on_grid(profesional.chairs, starts_at, clinic.tz, self.now)

    async def _book_first_free(
        self,
        appointments: AppointmentsService,
        data: Booking,
        candidatos: list[uuid.UUID],
        event_extra: dict[str, Any],
    ) -> Appointment:
        """Prueba cada sillón candidato en orden de id; el lock siempre es profesional → sillón."""
        for chair_id in candidatos:
            try:
                return await appointments.book(
                    replace(data, chair_id=chair_id),
                    origin=AppointmentOrigin.ONLINE,
                    event_extra=event_extra,
                )
            except DomainError as error:
                if error.status_code != 409 or error.detail not in _SLOT_LOST:
                    raise
        raise _SlotLostError

    async def _alternatives(
        self, clinic: PublicClinic, profesional: BookableProfessional, starts_at: datetime
    ) -> list[dict[str, Any]]:
        """Hasta 3 huecos del mismo profesional (todos los sillones), solo horarios e id."""
        slots = await self.offerable(
            clinic, profesional, starts_at, starts_at + ALTERNATIVES_HORIZON, cap=ALTERNATIVES
        )
        return [
            AlternativeSlot(
                starts_at=s.starts_at, ends_at=s.ends_at, professional_id=profesional.id
            ).model_dump(mode="json")
            for s in slots
        ]

    # ----------------------------------------------------------------- contacto

    @staticmethod
    def _contact(patient: PatientInput) -> Contact:
        """Tabla de D5: canal, aviso y errores genéricos (nunca el valor recibido, regla 13).

        Un email mal formado cuenta como ausente (no se guarda ni habilita el canal).
        """
        email = (patient.email or "").strip().lower()
        email_ok = bool(email) and len(email) <= EMAIL_MAX and bool(_EMAIL_RE.match(email))
        telefono = (patient.phone or "").strip()
        phone_e164: str | None = None
        if telefono:
            try:
                phone_e164 = normalize_phone_e164(telefono)
            except InvalidPhoneError:
                phone_e164 = None

        contacto: Contact
        if phone_e164 is not None:
            if patient.whatsapp_opt_in is True:
                contacto = Contact(phone_e164, email if email_ok else None, "whatsapp", True, ())
            elif patient.whatsapp_opt_in is False and email_ok:
                contacto = Contact(
                    phone_e164, email, "email", False, ("whatsapp_declined_email_channel",)
                )
            else:
                raise DomainError(422, "whatsapp_opt_in_required")
        elif email_ok:
            avisos = ("phone_invalid_email_channel",) if telefono else ()
            contacto = Contact(None, email, "email", False, avisos)
        else:
            raise DomainError(422, "contact_required")
        if not patient.privacy_accepted:
            raise DomainError(422, "privacy_consent_required")
        return contacto

    # ----------------------------------------------------------------- paciente

    async def _match_or_create(
        self, clinic: PublicClinic, patient: PatientInput, contacto: Contact
    ) -> Patient:
        """RN-ON-05: teléfono + nombre normalizados; sin teléfono válido, siempre uno nuevo."""
        nombre = patient.full_name.strip()
        if contacto.phone_e164 is not None:
            # Serializa el alta del mismo paciente nuevo (se libera al fin de la transacción).
            await self.session.execute(
                select(
                    func.pg_advisory_xact_lock(
                        func.hashtextextended(f"{clinic.id}{contacto.phone_e164}", 0)
                    )
                )
            )
            existente = await self.session.scalar(
                select(Patient)
                .where(
                    Patient.clinic_id == clinic.id,
                    Patient.archived_at.is_(None),
                    Patient.phone_e164 == contacto.phone_e164,
                    func.lower(func.btrim(Patient.full_name)) == func.lower(literal(nombre)),
                )
                .order_by(Patient.created_at, Patient.id)
                .limit(1)
            )
            if existente is not None:
                # Nunca se pisan nombre ni contactos guardados; el opt-in solo sube.
                if contacto.opt_in_granted and not existente.whatsapp_opt_in:
                    await ConsentService(self.session).record(
                        existente,
                        ReminderChannel.WHATSAPP,
                        ConsentStatus.OPT_IN,
                        ConsentSource.BOOKING,
                    )
                self._stamp_privacy(existente)
                await self.session.flush()
                return existente
        creado = await create_patient(
            self.session,
            clinic.id,
            full_name=nombre,
            phone=contacto.phone_e164,
            email=contacto.email,
            whatsapp_opt_in=contacto.opt_in_granted,
            consent_source=ConsentSource.BOOKING,
        )
        self._stamp_privacy(creado)
        await self.session.flush()
        return creado

    def _stamp_privacy(self, patient: Patient) -> None:
        patient.privacy_consent_at = self.now
        patient.privacy_consent_version = self.settings.PRIVACY_POLICY_VERSION
