"""Auditoría de configuración de agenda (C-04, US-001 CA-3).

El evento se agrega a la misma sesión que la mutación y se confirma con ella: si
la auditoría no se puede escribir, la mutación tampoco (espíritu de RN-GL-01).
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.principal import Principal
from app.models import AgendaConfigEvent, ConfigAction, ConfigEntity

Changes = dict[str, list[Any]]


def to_json(value: Any) -> Any:
    """Valor apto para `jsonb`: enums por valor, fechas ISO, uuid como texto."""
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, list):
        return [to_json(v) for v in value]
    if isinstance(value, dict):
        return {k: to_json(v) for k, v in value.items()}
    return value


def apply_changes(entity: Any, values: dict[str, Any]) -> Changes:
    """Asigna `values` sobre `entity` y devuelve `{campo: [anterior, nuevo]}` de lo que cambió."""
    cambios: Changes = {}
    for campo, nuevo in values.items():
        anterior = getattr(entity, campo)
        if anterior != nuevo:
            cambios[campo] = [to_json(anterior), to_json(nuevo)]
            setattr(entity, campo, nuevo)
    return cambios


def snapshot(entity: Any, fields: tuple[str, ...]) -> Changes:
    """Cambios de un alta: `{campo: [None, valor]}`."""
    return {campo: [None, to_json(getattr(entity, campo))] for campo in fields}


def action_for(changes: Changes) -> ConfigAction:
    """`deactivated`/`reactivated` si cambió `active`; si no, `updated`."""
    if "active" in changes:
        return ConfigAction.REACTIVATED if changes["active"][1] else ConfigAction.DEACTIVATED
    return ConfigAction.UPDATED


def record_config_event(
    session: AsyncSession,
    principal: Principal,
    *,
    entity: ConfigEntity,
    entity_id: uuid.UUID,
    action: ConfigAction,
    changes: Changes,
) -> None:
    """Agrega el evento a la transacción en curso (sin commit propio)."""
    session.add(
        AgendaConfigEvent(
            clinic_id=principal.clinic_id,
            actor_user_id=principal.user_id,
            entity=entity,
            entity_id=entity_id,
            action=action,
            changes=changes,
        )
    )
