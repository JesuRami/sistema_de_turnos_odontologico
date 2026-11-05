"""Escenario sintético de gestión por token (C-08): turno online con su token en claro.

Reloj fijo de la app en `AGENDA_NOW` (lunes 2030-01-07 08:00 Buenos Aires) vía la fixture
`agenda_clock`. Regla por defecto del profesional: lunes 09:00-13:00 de 30 min. El token se
genera como en C-07 (`secrets.token_urlsafe(32)`) y la base guarda solo su SHA-256. Todo dato
es ficticio (regla 13).
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from app.models import Appointment, AppointmentOrigin, AppointmentStatus, Patient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.booking_helpers import PublicBooking, make_booking
from tests.factories import make_appointment, make_patient, unique_email

NOMBRE_PACIENTE = "María Ficticia Prueba"


def new_token() -> str:
    """Token con el mismo formato que emite la reserva pública (43 caracteres url-safe)."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


@dataclass(frozen=True, slots=True)
class Managed:
    """Turno online gestionable: su reserva (clínica/profesional/sillón/regla) y el token."""

    booking: PublicBooking
    patient: Patient
    appointment: Appointment
    token: str

    @property
    def url(self) -> str:
        return f"/api/manage/{self.token}"


async def make_managed(
    db_session: AsyncSession,
    starts_at: datetime,
    *,
    booking: PublicBooking | None = None,
    status: AppointmentStatus = AppointmentStatus.PENDING,
    **overrides: Any,
) -> Managed:
    """Turno online persistido directo con un token nuevo; reutiliza `booking` si se pasa."""
    booking = booking or await make_booking(db_session)
    patient = await make_patient(
        db_session,
        booking.clinic,
        full_name=NOMBRE_PACIENTE,
        email=unique_email("maria.ficticia"),
    )
    token = new_token()
    appointment = await make_appointment(
        db_session,
        booking.clinic,
        patient=patient,
        professional=booking.professional,
        chair=booking.chair,
        starts_at=starts_at,
        status=status,
        origin=AppointmentOrigin.ONLINE,
        manage_token_hash=token_hash(token),
        **overrides,
    )
    return Managed(booking=booking, patient=patient, appointment=appointment, token=token)


async def get_view(client: httpx.AsyncClient, managed: Managed) -> httpx.Response:
    return await client.get(managed.url)
