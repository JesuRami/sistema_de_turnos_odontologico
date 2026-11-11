"""Bitácora de accesos clínicos (C-15, D5).

`record_access` agrega el evento a la **misma sesión** y hace `flush` inmediato (patrón de
`appointments/audit.py`): si el INSERT falla, falla la operación entera. Las lecturas también
escriben. El `payload` solo admite ids, conteos, versiones y códigos (nunca texto libre); la base
lo vuelve a exigir con el CHECK `payload_safe`.
"""

from __future__ import annotations

import enum
import re
import uuid
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.principal import Principal
from app.models import ClinicalAccessEvent, ClinicalAction
from app.modules.clinical.cursor import paginate_desc
from app.modules.clinical.schemas import AccessEventRead, AccessLogPage

PayloadValue = int | bool | str | uuid.UUID | enum.StrEnum | None
# Mismo criterio que el CHECK `payload_safe`: un string solo puede ser un código corto.
_CODE_RE = re.compile(r"^[0-9a-z_-]{1,64}$")


def _payload(valores: Mapping[str, PayloadValue] | None) -> dict[str, int | bool | str | None]:
    limpio: dict[str, int | bool | str | None] = {}
    for clave, valor in (valores or {}).items():
        if isinstance(valor, uuid.UUID | enum.StrEnum):
            limpio[clave] = str(valor)
        elif valor is None or isinstance(valor, int | bool):
            limpio[clave] = valor
        elif isinstance(valor, str) and _CODE_RE.match(valor):
            limpio[clave] = valor
        else:
            raise TypeError("payload de auditoría solo admite ids, conteos y códigos")
    return limpio


async def record_access(
    session: AsyncSession,
    principal: Principal,
    record_id: uuid.UUID,
    action: ClinicalAction,
    *,
    object_type: str | None = None,
    object_id: uuid.UUID | None = None,
    payload: Mapping[str, PayloadValue] | None = None,
) -> None:
    """Inserta el evento en la transacción en curso (sin commit)."""
    session.add(
        ClinicalAccessEvent(
            clinic_id=principal.clinic_id,
            record_id=record_id,
            actor_user_id=principal.user_id,
            action=action,
            object_type=object_type,
            object_id=object_id,
            payload=_payload(payload),
        )
    )
    await session.flush()


async def access_log_page(
    session: AsyncSession,
    principal: Principal,
    record_id: uuid.UUID,
    cursor: str | None,
    limit: int,
) -> AccessLogPage:
    """Eventos de una ficha, más recientes primero, por cursor."""
    stmt = select(
        ClinicalAccessEvent.id,
        ClinicalAccessEvent.actor_user_id,
        ClinicalAccessEvent.action,
        ClinicalAccessEvent.object_type,
        ClinicalAccessEvent.object_id,
        ClinicalAccessEvent.payload,
        ClinicalAccessEvent.created_at,
    ).where(
        ClinicalAccessEvent.clinic_id == principal.clinic_id,
        ClinicalAccessEvent.record_id == record_id,
    )
    filas, siguiente = await paginate_desc(
        session, stmt, ClinicalAccessEvent.created_at, ClinicalAccessEvent.id, cursor, limit
    )
    return AccessLogPage(items=[_evento(f) for f in filas], next_cursor=siguiente)


def _evento(fila: object) -> AccessEventRead:
    return AccessEventRead.model_validate(fila, from_attributes=True)
