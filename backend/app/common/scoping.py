"""Alcance por profesional aplicado en SQL (C-03 design §10).

Regla: toda consulta sobre datos con dueño profesional filtra **siempre** por
`clinic_id` del principal y, cuando el rol es exactamente `odontologo`, además
por su `professional_id`. `admin` y `recepcion` ven toda su clínica. El filtro
se agrega a la sentencia antes de `execute`; nunca se traen filas para
descartarlas en Python.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import InstrumentedAttribute

from app.common.exceptions import DomainError
from app.common.principal import Principal
from app.models import UserRole


def scope_by_professional(
    stmt: Select[Any],
    principal: Principal,
    professional_id_col: InstrumentedAttribute[Any],
) -> Select[Any]:
    """Acota `stmt` a la clínica del principal y, si corresponde, a su profesional.

    Un odontólogo sin `professional_id` corta con `403 forbidden_scope` en vez
    de comparar contra `NULL` (que devolvería filas de nadie o de todos).
    """
    stmt = stmt.where(professional_id_col.table.c.clinic_id == principal.clinic_id)
    if principal.roles == {UserRole.ODONTOLOGO}:
        if principal.professional_id is None:
            raise DomainError(403, "forbidden_scope")
        stmt = stmt.where(professional_id_col == principal.professional_id)
    return stmt


async def get_one_scoped_or_404(
    session: AsyncSession,
    stmt: Select[Any],
    id_col: InstrumentedAttribute[Any],
    row_id: uuid.UUID,
) -> Row[Any]:
    """Ejecuta una consulta ya acotada por `id` y responde `404` si no aparece.

    **Contrato para C-05**: el servicio arma `stmt` con las columnas que
    necesita, lo pasa por `scope_by_professional(...)` y luego llama a este
    helper. Pedir por identificador una fila de otro profesional (o de otra
    clínica) da `404 not_found`, nunca `403`, para no revelar existencia. No se
    debe usar `session.get()` directo para recursos con dueño profesional.
    """
    fila = (await session.execute(stmt.where(id_col == row_id).limit(1))).one_or_none()
    if fila is None:
        raise DomainError(404, "not_found")
    return fila
