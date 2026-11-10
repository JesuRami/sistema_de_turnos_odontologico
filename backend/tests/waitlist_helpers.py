"""Fábricas de la lista de espera (C-12): entradas y ofertas sintéticas persistidas directo.

Para invariantes de base y escenas de servicio. Solo datos ficticios (regla 13).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from app.models import (
    Chair,
    Clinic,
    Patient,
    Professional,
    ReminderChannel,
    ReminderJob,
    WaitingListEntry,
    WaitingListStatus,
    WaitlistOffer,
    WaitlistOfferStatus,
)
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_chair, make_clinic, make_patient, make_professional


@dataclass(frozen=True, slots=True)
class WaitScene:
    clinic: Clinic
    patient: Patient
    professional: Professional
    chair: Chair


async def make_wait_scene(session: AsyncSession, **clinic_overrides: Any) -> WaitScene:
    clinic = await make_clinic(session, **clinic_overrides)
    return WaitScene(
        clinic=clinic,
        patient=await make_patient(session, clinic),
        professional=await make_professional(session, clinic),
        chair=await make_chair(session, clinic),
    )


async def make_entry(
    session: AsyncSession,
    clinic: Clinic,
    patient: Patient,
    *,
    professional: Professional | None = None,
    date_from: date = date(2030, 1, 1),
    date_to: date = date(2030, 1, 31),
    **overrides: Any,
) -> WaitingListEntry:
    values: dict[str, Any] = {
        "clinic_id": clinic.id,
        "patient_id": patient.id,
        "professional_id": professional.id if professional else None,
        "date_from": date_from,
        "date_to": date_to,
        "status": WaitingListStatus.WAITING,
        "source": "reception",
    }
    values.update(overrides)
    entry = WaitingListEntry(**values)
    session.add(entry)
    await session.flush()
    return entry


async def make_offer(
    session: AsyncSession,
    entry: WaitingListEntry,
    *,
    professional: Professional,
    chair: Chair,
    starts_at: datetime,
    minutes: int = 30,
    expires_in: timedelta = timedelta(hours=4),
    now: datetime | None = None,
    **overrides: Any,
) -> WaitlistOffer:
    base = now or (starts_at - timedelta(days=1))
    values: dict[str, Any] = {
        "clinic_id": entry.clinic_id,
        "entry_id": entry.id,
        "professional_id": professional.id,
        "chair_id": chair.id,
        "starts_at": starts_at,
        "ends_at": starts_at + timedelta(minutes=minutes),
        "expires_at": min(base + expires_in, starts_at),
        "status": WaitlistOfferStatus.PENDING,
        "mode": "auto",
    }
    values.update(overrides)
    offer = WaitlistOffer(**values)
    session.add(offer)
    await session.flush()
    return offer


# ----------------------------------------------------------------- motor (commits reales)


@dataclass(frozen=True, slots=True)
class OfferScene:
    scene: WaitScene
    entry: WaitingListEntry
    offer: WaitlistOffer
    job: ReminderJob


async def commit_offer_scene(
    maker: Any,
    *,
    now: datetime,
    starts_in: timedelta = timedelta(days=2),
    expires_in: timedelta = timedelta(hours=4),
    channel: ReminderChannel = ReminderChannel.WHATSAPP,
    opt_in: bool = True,
    email: str | None = None,
    offer_status: WaitlistOfferStatus = WaitlistOfferStatus.PENDING,
    templates: bool = True,
) -> OfferScene:
    """Oferta pendiente con su job `waitlist_offer` disponible ya, todo commiteado."""
    from app.modules.reminders.seeding import seed_default_templates

    async with maker() as session:
        clinic = await make_clinic(session)
        if templates:
            await seed_default_templates(session, clinic.id)
        patient = await make_patient(session, clinic, whatsapp_opt_in=opt_in, email=email)
        professional = await make_professional(session, clinic, display_name="Dra. Ficticia Oferta")
        chair = await make_chair(session, clinic)
        scene = WaitScene(clinic, patient, professional, chair)
        entry = await make_entry(
            session, clinic, patient, status=WaitingListStatus.OFFERED, date_to=date(2030, 2, 28)
        )
        starts_at = now + starts_in
        offer = await make_offer(
            session,
            entry,
            professional=professional,
            chair=chair,
            starts_at=starts_at,
            now=now,
            expires_in=expires_in,
            status=offer_status,
        )
        job = ReminderJob(
            clinic_id=clinic.id,
            waitlist_offer_id=offer.id,
            step="waitlist_offer",
            channel=channel,
            scheduled_for=now - timedelta(minutes=1),
            available_at=now - timedelta(minutes=1),
            starts_at_snapshot=starts_at,
        )
        session.add(job)
        await session.commit()
    return OfferScene(scene, entry, offer, job)


# ----------------------------------------------------------------------------- API

URL = "/api/waiting-list"


def entry_body(patient: Patient, **cambios: Any) -> dict[str, Any]:
    """Cuerpo mínimo válido con el reloj de la app en `AGENDA_NOW` (lunes 07/01/2030)."""
    cuerpo: dict[str, Any] = {
        "patient_id": str(patient.id),
        "professional_id": None,
        "date_from": "2030-01-08",
        "date_to": "2030-01-20",
    }
    cuerpo.update(cambios)
    return cuerpo
