"""Odontograma FDI (C-15, D3, spec `clinical/odontogram`).

- Alta por lotes (1–32) en una transacción: todo o nada. Validaciones de estado (misma clínica,
  activo, alcance cara/pieza) y de evolución (misma ficha) antes de insertar.
- Estado vigente = `DISTINCT ON (tooth, surface)` sobre `odontogram_event` ordenado por
  `(created_at DESC, id DESC)` (índice `ix_odontogram_event_projection`); "limpiar" (estado nulo)
  tapa lo anterior. Nunca una tabla de estado mutable (regla 8).
- Historial por pieza, más reciente primero, por cursor.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, insert, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import DomainError
from app.common.principal import Principal
from app.models import (
    ClinicalAction,
    ClinicalEvolution,
    OdontogramCondition,
    OdontogramEvent,
    ToothSurface,
)
from app.modules.clinical.access import resolve_record
from app.modules.clinical.audit import record_access
from app.modules.clinical.cursor import paginate_desc
from app.modules.clinical.fdi import Dentition, dentition_of, is_valid_tooth, teeth_of
from app.modules.clinical.schemas import (
    ConditionRead,
    ConditionsList,
    DentitionName,
    OdontogramBatch,
    OdontogramEventRead,
    OdontogramEventsCreated,
    OdontogramRead,
    SurfaceState,
    ToothHistoryPage,
    ToothState,
)

SURFACES = ("M", "D", "O", "V", "L", "W")
_RANGES: dict[str, tuple[int, int]] = {"permanent": (11, 48), "deciduous": (51, 85)}

_EVENT_COLUMNS = (
    OdontogramEvent.id,
    OdontogramEvent.tooth,
    OdontogramEvent.surface,
    OdontogramEvent.condition_id,
    OdontogramEvent.note,
    OdontogramEvent.evolution_id,
    OdontogramEvent.professional_id,
    OdontogramEvent.created_by_user_id,
    OdontogramEvent.created_at,
)


def projection_statement(
    clinic_id: uuid.UUID, record_id: uuid.UUID, dentition: Dentition
) -> Select[Any]:
    """Última entrada por (pieza, cara) de la dentición pedida (columnas explícitas)."""
    desde, hasta = _RANGES[dentition]
    return (
        select(
            OdontogramEvent.tooth,
            OdontogramEvent.surface,
            OdontogramEvent.condition_id,
            OdontogramEvent.id,
            OdontogramEvent.created_at,
        )
        .distinct(OdontogramEvent.tooth, OdontogramEvent.surface)
        .where(
            OdontogramEvent.record_id == record_id,
            OdontogramEvent.clinic_id == clinic_id,
            OdontogramEvent.tooth.between(desde, hasta),
        )
        .order_by(
            OdontogramEvent.tooth,
            OdontogramEvent.surface,
            OdontogramEvent.created_at.desc(),
            OdontogramEvent.id.desc(),
        )
    )


def _event_read(fila: Row[Any]) -> OdontogramEventRead:
    return OdontogramEventRead(
        id=fila.id,
        tooth=fila.tooth,
        surface=str(fila.surface),  # type: ignore[arg-type]
        dentition=dentition_of(fila.tooth),
        condition_id=fila.condition_id,
        condition_code=fila.condition_code,
        condition_label=fila.condition_label,
        note=fila.note,
        evolution_id=fila.evolution_id,
        professional_id=fila.professional_id,
        created_by_user_id=fila.created_by_user_id,
        created_at=fila.created_at,
    )


class OdontogramService:
    def __init__(self, session: AsyncSession, principal: Principal) -> None:
        self.session = session
        self.principal = principal

    async def conditions(self) -> ConditionsList:
        filas = (
            await self.session.execute(
                select(
                    OdontogramCondition.id,
                    OdontogramCondition.code,
                    OdontogramCondition.label,
                    OdontogramCondition.category,
                    OdontogramCondition.scope,
                    OdontogramCondition.active,
                )
                .where(OdontogramCondition.clinic_id == self.principal.clinic_id)
                .order_by(OdontogramCondition.label, OdontogramCondition.id)
            )
        ).all()
        return ConditionsList(
            items=[ConditionRead.model_validate(f, from_attributes=True) for f in filas]
        )

    async def _check_conditions(self, batch: OdontogramBatch) -> dict[uuid.UUID, Row[Any]]:
        ids = {e.condition_id for e in batch.entries if e.condition_id is not None}
        if not ids:
            return {}
        filas = (
            await self.session.execute(
                select(
                    OdontogramCondition.id,
                    OdontogramCondition.code,
                    OdontogramCondition.label,
                    OdontogramCondition.scope,
                    OdontogramCondition.active,
                ).where(
                    OdontogramCondition.clinic_id == self.principal.clinic_id,
                    OdontogramCondition.id.in_(ids),
                )
            )
        ).all()
        por_id = {f.id: f for f in filas}
        for entrada in batch.entries:
            if entrada.condition_id is None:
                continue
            estado = por_id.get(entrada.condition_id)
            if estado is None:
                raise DomainError(422, "condition_not_found")
            if not estado.active:
                raise DomainError(422, "condition_inactive")
            if (estado.scope == "tooth") != (entrada.surface == "W"):
                raise DomainError(422, "condition_scope_mismatch")
        return por_id

    async def _check_evolutions(self, record_id: uuid.UUID, batch: OdontogramBatch) -> None:
        ids = {e.evolution_id for e in batch.entries if e.evolution_id is not None}
        if not ids:
            return
        encontradas = set(
            (
                await self.session.execute(
                    select(ClinicalEvolution.id).where(
                        ClinicalEvolution.clinic_id == self.principal.clinic_id,
                        ClinicalEvolution.record_id == record_id,
                        ClinicalEvolution.id.in_(ids),
                    )
                )
            ).scalars()
        )
        if encontradas != ids:
            raise DomainError(422, "evolution_not_found")

    async def record_events(
        self, record_id: uuid.UUID, batch: OdontogramBatch
    ) -> OdontogramEventsCreated:
        claves = [(e.tooth, e.surface) for e in batch.entries]
        if len(set(claves)) != len(claves):
            raise DomainError(422, "duplicate_entry")
        ficha = await resolve_record(self.session, self.principal, record_id, write=True)
        estados = await self._check_conditions(batch)
        await self._check_evolutions(ficha.id, batch)
        assert self.principal.professional_id is not None  # garantizado por ClinicalWriter
        filas = (
            await self.session.execute(
                insert(OdontogramEvent).returning(*_EVENT_COLUMNS, sort_by_parameter_order=True),
                [
                    {
                        "clinic_id": ficha.clinic_id,
                        "record_id": ficha.id,
                        "tooth": e.tooth,
                        "surface": ToothSurface(e.surface),
                        "condition_id": e.condition_id,
                        "note": e.note,
                        "evolution_id": e.evolution_id,
                        "professional_id": self.principal.professional_id,
                        "created_by_user_id": self.principal.user_id,
                    }
                    for e in batch.entries
                ],
            )
        ).all()
        await record_access(
            self.session,
            self.principal,
            ficha.id,
            ClinicalAction.ODONTOGRAM_WRITE,
            payload={"entries": len(filas)},
        )
        await self.session.commit()
        items = []
        for fila in filas:
            estado = estados.get(fila.condition_id) if fila.condition_id else None
            items.append(
                OdontogramEventRead(
                    id=fila.id,
                    tooth=fila.tooth,
                    surface=str(fila.surface),  # type: ignore[arg-type]
                    dentition=dentition_of(fila.tooth),
                    condition_id=fila.condition_id,
                    condition_code=estado.code if estado else None,
                    condition_label=estado.label if estado else None,
                    note=fila.note,
                    evolution_id=fila.evolution_id,
                    professional_id=fila.professional_id,
                    created_by_user_id=fila.created_by_user_id,
                    created_at=fila.created_at,
                )
            )
        return OdontogramEventsCreated(items=items)

    async def current(self, record_id: uuid.UUID, dentition: DentitionName) -> OdontogramRead:
        ficha = await resolve_record(self.session, self.principal, record_id)
        proyeccion = projection_statement(ficha.clinic_id, ficha.id, dentition).subquery()
        filas: Sequence[Row[Any]] = (
            await self.session.execute(
                select(
                    proyeccion.c.tooth,
                    proyeccion.c.surface,
                    proyeccion.c.condition_id,
                    proyeccion.c.id,
                    proyeccion.c.created_at,
                    OdontogramCondition.code,
                    OdontogramCondition.label,
                ).outerjoin(
                    OdontogramCondition,
                    (OdontogramCondition.clinic_id == ficha.clinic_id)
                    & (OdontogramCondition.id == proyeccion.c.condition_id),
                )
            )
        ).all()
        vigentes = {(f.tooth, str(f.surface)): f for f in filas if f.condition_id is not None}
        piezas = []
        for tooth in teeth_of(dentition):
            caras = []
            for cara in SURFACES:
                f = vigentes.get((tooth, cara))
                caras.append(
                    SurfaceState(
                        surface=cara,  # type: ignore[arg-type]
                        condition_id=f.condition_id if f else None,
                        condition_code=f.code if f else None,
                        condition_label=f.label if f else None,
                        event_id=f.id if f else None,
                        recorded_at=f.created_at if f else None,
                    )
                )
            piezas.append(ToothState(tooth=tooth, surfaces=caras))
        await record_access(
            self.session,
            self.principal,
            ficha.id,
            ClinicalAction.ODONTOGRAM_READ,
            payload={"dentition": dentition},
        )
        await self.session.commit()
        return OdontogramRead(dentition=dentition, teeth=piezas)

    async def history(
        self, record_id: uuid.UUID, tooth: int, cursor: str | None, limit: int
    ) -> ToothHistoryPage:
        if not is_valid_tooth(tooth):
            raise DomainError(422, "invalid_tooth")
        ficha = await resolve_record(self.session, self.principal, record_id)
        stmt = (
            select(
                *_EVENT_COLUMNS,
                OdontogramCondition.code.label("condition_code"),
                OdontogramCondition.label.label("condition_label"),
            )
            .outerjoin(
                OdontogramCondition,
                (OdontogramCondition.clinic_id == OdontogramEvent.clinic_id)
                & (OdontogramCondition.id == OdontogramEvent.condition_id),
            )
            .where(
                OdontogramEvent.clinic_id == ficha.clinic_id,
                OdontogramEvent.record_id == ficha.id,
                OdontogramEvent.tooth == tooth,
            )
        )
        filas, siguiente = await paginate_desc(
            self.session, stmt, OdontogramEvent.created_at, OdontogramEvent.id, cursor, limit
        )
        await record_access(
            self.session,
            self.principal,
            ficha.id,
            ClinicalAction.ODONTOGRAM_HISTORY_READ,
            payload={"tooth": tooth},
        )
        await self.session.commit()
        return ToothHistoryPage(items=[_event_read(f) for f in filas], next_cursor=siguiente)
