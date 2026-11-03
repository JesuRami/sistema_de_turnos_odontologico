"""Escenario sintético de configuración de agenda: una clínica con sus tres roles."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.core.settings import Settings
from app.models import (
    AgendaConfigEvent,
    Chair,
    Clinic,
    ConfigAction,
    ConfigEntity,
    Professional,
    User,
    UserRole,
)
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.auth_helpers import issue_session
from tests.factories import make_chair, make_clinic, make_professional, make_user, unique_email


@dataclass(frozen=True, slots=True)
class Staff:
    """Clínica con admin, recepción y un odontólogo atado a `professional`."""

    clinic: Clinic
    admin: User
    professional: Professional
    chair: Chair
    headers: dict[str, dict[str, str]]


async def make_staff(db_session: AsyncSession, redis_client: Redis, settings: Settings) -> Staff:
    """Crea la clínica, un profesional, un sillón y una sesión por rol."""
    clinic = await make_clinic(db_session)
    professional = await make_professional(db_session, clinic)
    chair = await make_chair(db_session, clinic)
    usuarios = {
        UserRole.ADMIN: await make_user(
            db_session, clinic, email=unique_email("admin.ficticio"), must_change_password=False
        ),
        UserRole.RECEPCION: await make_user(
            db_session,
            clinic,
            email=unique_email("recepcion.ficticia"),
            role=UserRole.RECEPCION,
            must_change_password=False,
        ),
        UserRole.ODONTOLOGO: await make_user(
            db_session,
            clinic,
            email=unique_email("odontologo.ficticio"),
            role=UserRole.ODONTOLOGO,
            professional_id=professional.id,
            must_change_password=False,
        ),
    }
    headers = {
        rol.value: (await issue_session(redis_client, settings, user)).headers
        for rol, user in usuarios.items()
    }
    return Staff(
        clinic=clinic,
        admin=usuarios[UserRole.ADMIN],
        professional=professional,
        chair=chair,
        headers=headers,
    )


async def config_events(
    db_session: AsyncSession, entity: ConfigEntity, entity_id: uuid.UUID
) -> list[AgendaConfigEvent]:
    """Eventos de auditoría de una entidad, del más viejo al más nuevo."""
    stmt = (
        select(AgendaConfigEvent)
        .where(AgendaConfigEvent.entity == entity, AgendaConfigEvent.entity_id == entity_id)
        .order_by(AgendaConfigEvent.created_at, AgendaConfigEvent.id)
    )
    return list((await db_session.execute(stmt)).scalars().all())


def actions(eventos: list[AgendaConfigEvent]) -> list[ConfigAction]:
    """Acciones auditadas en orden."""
    return [e.action for e in eventos]
