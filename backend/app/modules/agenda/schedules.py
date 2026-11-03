"""Servicio de plantilla semanal (C-04, US-002, RN-AG-05).

El anti-solape lo garantiza el EXCLUDE `ex_schedule_rule_no_overlap` en la base
(regla 1): el servicio no pre-chequea en Python (sería carrera); traduce la
violación a `409 schedule_overlap` y adjunta las reglas en conflicto.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, time
from typing import Any, NoReturn

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import DomainError
from app.common.pagination import paginate_entities
from app.common.principal import Principal
from app.common.scoping import scope_by_professional
from app.models import Chair, ConfigAction, ConfigEntity, Professional, ScheduleRule
from app.modules.agenda.audit import action_for, apply_changes, record_config_event, snapshot
from app.modules.agenda.schemas import (
    ScheduleRuleCreate,
    ScheduleRulePage,
    ScheduleRuleRead,
    ScheduleRuleUpdate,
)
from app.modules.agenda.service import assert_bookable_resource

_EXCLUDE = "ex_schedule_rule_no_overlap"
_RULE_FIELDS = (
    "professional_id",
    "chair_id",
    "weekday",
    "start_time",
    "end_time",
    "slot_duration_min",
    "valid_from",
    "valid_to",
    "active",
)
_OVERLAP_KEYS = ("professional_id", "chair_id", "weekday", "start_time", "end_time")


class SchedulesService:
    """Casos de uso de la plantilla semanal de una clínica."""

    def __init__(self, session: AsyncSession, principal: Principal) -> None:
        self.session = session
        self.principal = principal

    async def _rule(self, rule_id: uuid.UUID) -> ScheduleRule:
        stmt = scope_by_professional(
            select(ScheduleRule), self.principal, ScheduleRule.professional_id
        )
        encontrada: ScheduleRule | None = (
            await self.session.execute(stmt.where(ScheduleRule.id == rule_id))
        ).scalar_one_or_none()
        if encontrada is None:
            raise DomainError(404, "not_found")
        return encontrada

    async def list(
        self,
        professional_id: uuid.UUID | None,
        chair_id: uuid.UUID | None,
        active: bool | None,
        cursor: str | None,
        limit: int,
    ) -> ScheduleRulePage:
        stmt = scope_by_professional(
            select(ScheduleRule), self.principal, ScheduleRule.professional_id
        )
        if professional_id is not None:
            stmt = stmt.where(ScheduleRule.professional_id == professional_id)
        if chair_id is not None:
            stmt = stmt.where(ScheduleRule.chair_id == chair_id)
        if active is not None:
            stmt = stmt.where(ScheduleRule.active.is_(active))
        filas, siguiente = await paginate_entities(
            self.session, stmt, ScheduleRule.created_at, ScheduleRule.id, cursor, limit
        )
        return ScheduleRulePage(
            items=[ScheduleRuleRead.model_validate(f) for f in filas], next_cursor=siguiente
        )

    async def get(self, rule_id: uuid.UUID) -> ScheduleRuleRead:
        return ScheduleRuleRead.model_validate(await self._rule(rule_id))

    async def create(self, payload: ScheduleRuleCreate) -> ScheduleRuleRead:
        await assert_bookable_resource(
            self.session, self.principal, Professional, payload.professional_id
        )
        await assert_bookable_resource(self.session, self.principal, Chair, payload.chair_id)
        valores = payload.model_dump()
        rule = ScheduleRule(clinic_id=self.principal.clinic_id, **valores)
        try:
            async with self.session.begin_nested():
                self.session.add(rule)
                await self.session.flush()
        except IntegrityError as exc:
            await self._raise_integrity(exc, {**valores, "id": None})
        await self.session.refresh(rule)
        record_config_event(
            self.session,
            self.principal,
            entity=ConfigEntity.SCHEDULE_RULE,
            entity_id=rule.id,
            action=ConfigAction.CREATED,
            changes=snapshot(rule, _RULE_FIELDS),
        )
        await self.session.commit()
        return ScheduleRuleRead.model_validate(rule)

    async def update(self, rule_id: uuid.UUID, payload: ScheduleRuleUpdate) -> ScheduleRuleRead:
        rule = await self._rule(rule_id)
        efectivos: dict[str, Any] = {}
        try:
            # Los cambios se aplican DENTRO del savepoint: `begin_nested()` hace flush de lo
            # pendiente antes de abrirlo, y un fallo ahí invalidaría la transacción entera.
            async with self.session.begin_nested():
                cambios = apply_changes(rule, payload.model_dump(include=payload.model_fields_set))
                # Valores efectivos antes del flush: si el savepoint revierte, `rule` expira.
                efectivos = {
                    k: getattr(rule, k) for k in (*_OVERLAP_KEYS, "valid_from", "valid_to", "id")
                }
                await self.session.flush()
        except IntegrityError as exc:
            await self._raise_integrity(exc, efectivos)
        if not cambios:
            return ScheduleRuleRead.model_validate(rule)
        record_config_event(
            self.session,
            self.principal,
            entity=ConfigEntity.SCHEDULE_RULE,
            entity_id=rule.id,
            action=action_for(cambios),
            changes=cambios,
        )
        await self.session.commit()
        await self.session.refresh(rule)
        return ScheduleRuleRead.model_validate(rule)

    async def _raise_integrity(self, exc: IntegrityError, valores: dict[str, Any]) -> NoReturn:
        """EXCLUDE → `409` con conflictos; cualquier otro constraint → `422` genérico."""
        if _EXCLUDE in str(exc.orig):
            conflictos = await self._conflicts(valores)
            raise DomainError(
                409, "schedule_overlap", extra={"conflicts": [str(c) for c in conflictos]}
            ) from None
        raise DomainError(422, "invalid_schedule_rule") from None

    async def _conflicts(self, valores: dict[str, Any]) -> Sequence[uuid.UUID]:
        """Reglas activas que intersectan franja y vigencia (mismo predicado que el EXCLUDE)."""
        inicio: time = valores["start_time"]
        fin: time = valores["end_time"]
        desde: date = valores["valid_from"]
        hasta: date | None = valores["valid_to"]
        stmt = select(ScheduleRule.id).where(
            ScheduleRule.clinic_id == self.principal.clinic_id,
            ScheduleRule.professional_id == valores["professional_id"],
            ScheduleRule.chair_id == valores["chair_id"],
            ScheduleRule.weekday == valores["weekday"],
            ScheduleRule.active.is_(True),
            ScheduleRule.start_time < fin,
            ScheduleRule.end_time > inicio,
            or_(ScheduleRule.valid_to.is_(None), ScheduleRule.valid_to >= desde),
        )
        if hasta is not None:
            stmt = stmt.where(ScheduleRule.valid_from <= hasta)
        if valores["id"] is not None:
            stmt = stmt.where(ScheduleRule.id != valores["id"])
        return (await self.session.execute(stmt.order_by(ScheduleRule.id))).scalars().all()
