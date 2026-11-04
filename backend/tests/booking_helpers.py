"""Escenario sintético de la reserva pública (C-07): clínica habilitada con profesional y sillón.

Reloj fijo de la app en `AGENDA_NOW` (lunes 2030-01-07 08:00 Buenos Aires) vía la fixture
`agenda_clock`. Regla por defecto: lunes 09:00-13:00 de 30 min. Todo dato es ficticio (regla 13).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
from app.core.settings import Settings
from app.models import Chair, Clinic, Professional, ScheduleRule
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.conftest import AGENDA_NOW
from tests.factories import (
    make_chair,
    make_clinic,
    make_professional,
    make_schedule_rule,
)

NOMBRE = "Lucía Inventada Ficticia"
TELEFONO_NACIONAL = "011 15 5555-0123"
TELEFONO_E164 = "+5491155550123"
EMAIL = "lucia.inventada@example.com"


@dataclass(frozen=True, slots=True)
class PublicBooking:
    clinic: Clinic
    professional: Professional
    chair: Chair
    rule: ScheduleRule

    @property
    def slug(self) -> str:
        return self.clinic.slug


async def make_booking(
    db_session: AsyncSession,
    *,
    buffer_min: int = 0,
    clinic: Clinic | None = None,
    **rule: Any,
) -> PublicBooking:
    """Clínica con reserva habilitada, un profesional reservable, un sillón y su regla."""
    clinic = clinic or await make_clinic(db_session, booking_enabled=True)
    professional = await make_professional(db_session, clinic, buffer_min=buffer_min)
    chair = await make_chair(db_session, clinic)
    regla = await make_schedule_rule(db_session, clinic, professional, chair, **rule)
    return PublicBooking(clinic=clinic, professional=professional, chair=chair, rule=regla)


def reserva(booking: PublicBooking, starts_at: str, **patient: Any) -> dict[str, Any]:
    """Cuerpo válido de `POST /api/booking/{slug}/appointments` (teléfono nacional + opt-in)."""
    datos: dict[str, Any] = {
        "full_name": NOMBRE,
        "phone": TELEFONO_NACIONAL,
        "whatsapp_opt_in": True,
        "privacy_accepted": True,
    }
    datos.update(patient)
    return {
        "professional_id": str(booking.professional.id),
        "starts_at": starts_at,
        "patient": datos,
    }


def committed_app(engine: AsyncEngine, redis: Redis, settings: Settings) -> FastAPI:
    """App cuyas dependencias de DB/Redis/reloj apuntan a `engine` (commits reales)."""
    from app.common.clock import get_now
    from app.core.deps import get_db
    from app.core.redis import get_redis
    from app.main import create_app

    app = create_app(settings)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _db() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    async def _redis() -> Redis:
        return redis

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_redis] = _redis
    app.dependency_overrides[get_now] = lambda: AGENDA_NOW
    app.state.sessionmaker = maker
    return app


def client_for(app: FastAPI, ip: str = "127.0.0.1") -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(ip, 12345)),
        base_url="http://test",
        timeout=30.0,
    )
