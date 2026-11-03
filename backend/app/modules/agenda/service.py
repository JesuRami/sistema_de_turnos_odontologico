"""Servicio de recursos de agenda: profesionales y sillones (C-04, US-001).

Reglas: todo filtro usa el `clinic_id` del principal (regla 4); el odontólogo
solo ve su propio profesional vía `scope_by_professional` (C-03); la baja es
lógica (`active=false`, regla 7); cada mutación audita en la misma transacción.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import DomainError
from app.common.pagination import paginate_entities
from app.common.principal import Principal
from app.common.scoping import scope_by_professional
from app.models import Chair, ConfigAction, ConfigEntity, Professional
from app.modules.agenda.audit import action_for, apply_changes, record_config_event, snapshot
from app.modules.agenda.schemas import (
    ChairCreate,
    ChairPage,
    ChairRead,
    ChairUpdate,
    ProfessionalCreate,
    ProfessionalPage,
    ProfessionalRead,
    ProfessionalUpdate,
)

_PROFESSIONAL_FIELDS = (
    "display_name",
    "color",
    "default_duration_min",
    "buffer_min",
    "booking_enabled",
    "active",
)
_CHAIR_FIELDS = ("name", "active")


async def assert_bookable_resource(
    session: AsyncSession,
    principal: Principal,
    model: type[Professional] | type[Chair],
    resource_id: uuid.UUID,
) -> None:
    """El recurso del body debe ser de la clínica (`422 invalid_resource`) y estar activo.

    Un recurso de otra clínica responde igual que uno inexistente: no se revela.
    """
    activo = await session.scalar(
        select(model.active).where(model.id == resource_id, model.clinic_id == principal.clinic_id)
    )
    if activo is None:
        raise DomainError(422, "invalid_resource")
    if not activo:
        raise DomainError(422, "resource_inactive")


class ResourcesService:
    """Casos de uso de profesionales y sillones de una clínica."""

    def __init__(self, session: AsyncSession, principal: Principal) -> None:
        self.session = session
        self.principal = principal

    # ----------------------------------------------------------- profesionales

    async def _professional(self, professional_id: uuid.UUID) -> Professional:
        stmt = scope_by_professional(select(Professional), self.principal, Professional.id)
        encontrado: Professional | None = (
            await self.session.execute(stmt.where(Professional.id == professional_id))
        ).scalar_one_or_none()
        if encontrado is None:
            raise DomainError(404, "not_found")
        return encontrado

    async def list_professionals(
        self, active: bool | None, cursor: str | None, limit: int
    ) -> ProfessionalPage:
        stmt = scope_by_professional(select(Professional), self.principal, Professional.id)
        if active is not None:
            stmt = stmt.where(Professional.active.is_(active))
        filas, siguiente = await paginate_entities(
            self.session, stmt, Professional.created_at, Professional.id, cursor, limit
        )
        return ProfessionalPage(
            items=[ProfessionalRead.model_validate(f) for f in filas], next_cursor=siguiente
        )

    async def get_professional(self, professional_id: uuid.UUID) -> ProfessionalRead:
        return ProfessionalRead.model_validate(await self._professional(professional_id))

    async def create_professional(self, payload: ProfessionalCreate) -> ProfessionalRead:
        professional = Professional(clinic_id=self.principal.clinic_id, **payload.model_dump())
        self.session.add(professional)
        await self.session.flush()
        await self.session.refresh(professional)
        record_config_event(
            self.session,
            self.principal,
            entity=ConfigEntity.PROFESSIONAL,
            entity_id=professional.id,
            action=ConfigAction.CREATED,
            changes=snapshot(professional, _PROFESSIONAL_FIELDS),
        )
        await self.session.commit()
        return ProfessionalRead.model_validate(professional)

    async def update_professional(
        self, professional_id: uuid.UUID, payload: ProfessionalUpdate
    ) -> ProfessionalRead:
        professional = await self._professional(professional_id)
        await self._audited_update(
            ConfigEntity.PROFESSIONAL,
            professional,
            payload.model_dump(include=payload.model_fields_set),
        )
        return ProfessionalRead.model_validate(professional)

    # --------------------------------------------------------------- sillones

    async def _chair(self, chair_id: uuid.UUID) -> Chair:
        """Los sillones no tienen dueño profesional: todo el personal de la clínica los lee."""
        encontrado = (
            await self.session.execute(
                select(Chair).where(
                    Chair.id == chair_id, Chair.clinic_id == self.principal.clinic_id
                )
            )
        ).scalar_one_or_none()
        if encontrado is None:
            raise DomainError(404, "not_found")
        return encontrado

    async def list_chairs(self, active: bool | None, cursor: str | None, limit: int) -> ChairPage:
        stmt = select(Chair).where(Chair.clinic_id == self.principal.clinic_id)
        if active is not None:
            stmt = stmt.where(Chair.active.is_(active))
        filas, siguiente = await paginate_entities(
            self.session, stmt, Chair.created_at, Chair.id, cursor, limit
        )
        return ChairPage(items=[ChairRead.model_validate(f) for f in filas], next_cursor=siguiente)

    async def get_chair(self, chair_id: uuid.UUID) -> ChairRead:
        return ChairRead.model_validate(await self._chair(chair_id))

    async def create_chair(self, payload: ChairCreate) -> ChairRead:
        chair = Chair(clinic_id=self.principal.clinic_id, name=payload.name)
        self.session.add(chair)
        await self.session.flush()
        await self.session.refresh(chair)
        record_config_event(
            self.session,
            self.principal,
            entity=ConfigEntity.CHAIR,
            entity_id=chair.id,
            action=ConfigAction.CREATED,
            changes=snapshot(chair, _CHAIR_FIELDS),
        )
        await self.session.commit()
        return ChairRead.model_validate(chair)

    async def update_chair(self, chair_id: uuid.UUID, payload: ChairUpdate) -> ChairRead:
        chair = await self._chair(chair_id)
        await self._audited_update(
            ConfigEntity.CHAIR, chair, payload.model_dump(include=payload.model_fields_set)
        )
        return ChairRead.model_validate(chair)

    # ---------------------------------------------------------------- helpers

    async def _audited_update(
        self, entity: ConfigEntity, row: Professional | Chair, values: dict[str, Any]
    ) -> None:
        cambios = apply_changes(row, values)
        if not cambios:
            return
        await self.session.flush()
        record_config_event(
            self.session,
            self.principal,
            entity=entity,
            entity_id=row.id,
            action=action_for(cambios),
            changes=cambios,
        )
        await self.session.commit()
        await self.session.refresh(row)
