"""Servicio de bloqueos de agenda (C-04, US-003, RN-BL-01/03/04).

- RN-BL-01: al menos un objetivo (schema + CHECK en la base).
- RN-BL-03: terminado = inmutable; en curso = solo se mueve el fin (a un instante
  no pasado); futuro = editable o retirable. El retiro es lógico (`removed_at`).
- RN-BL-04: el cierre de clínica crea un bloqueo por sillón activo, atómico.
- RN-BL-02 (bloqueo que pisa turnos vigentes) llega con `appointment` en C-05:
  ese change agrega el chequeo a `create`/`update` de este servicio.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import DomainError
from app.common.pagination import paginate_entities
from app.common.principal import Principal
from app.common.scoping import scope_by_professional
from app.models import Block, Chair, ConfigAction, ConfigEntity, Professional, UserRole
from app.modules.agenda.audit import apply_changes, record_config_event, snapshot, to_json
from app.modules.agenda.schemas import (
    BlockCreate,
    BlockList,
    BlockPage,
    BlockRead,
    BlockUpdate,
    ClosureCreate,
)
from app.modules.agenda.service import assert_bookable_resource

_BLOCK_FIELDS = ("professional_id", "chair_id", "starts_at", "ends_at", "reason", "notes")


def _now() -> datetime:
    return datetime.now(UTC)


class BlocksService:
    """Casos de uso de bloqueos de una clínica."""

    def __init__(self, session: AsyncSession, principal: Principal) -> None:
        self.session = session
        self.principal = principal

    async def _block(self, block_id: uuid.UUID) -> Block:
        """Bloqueo vigente (no retirado) dentro del alcance del principal, o `404`."""
        stmt = scope_by_professional(select(Block), self.principal, Block.professional_id)
        encontrado: Block | None = (
            await self.session.execute(stmt.where(Block.id == block_id, Block.removed_at.is_(None)))
        ).scalar_one_or_none()
        if encontrado is None:
            raise DomainError(404, "not_found")
        return encontrado

    # ---------------------------------------------------------------- lectura

    async def list(
        self,
        desde: datetime | None,
        hasta: datetime | None,
        professional_id: uuid.UUID | None,
        chair_id: uuid.UUID | None,
        cursor: str | None,
        limit: int,
    ) -> BlockPage:
        """Bloqueos vigentes que intersectan `[desde, hasta)`, por `starts_at`."""
        if desde is not None and hasta is not None and hasta <= desde:
            raise DomainError(422, "invalid_range")
        stmt = scope_by_professional(select(Block), self.principal, Block.professional_id).where(
            Block.removed_at.is_(None)
        )
        if desde is not None:
            stmt = stmt.where(Block.ends_at > desde)
        if hasta is not None:
            stmt = stmt.where(Block.starts_at < hasta)
        if professional_id is not None:
            stmt = stmt.where(Block.professional_id == professional_id)
        if chair_id is not None:
            stmt = stmt.where(Block.chair_id == chair_id)
        filas, siguiente = await paginate_entities(
            self.session, stmt, Block.starts_at, Block.id, cursor, limit
        )
        return BlockPage(items=[BlockRead.model_validate(f) for f in filas], next_cursor=siguiente)

    async def get(self, block_id: uuid.UUID) -> BlockRead:
        return BlockRead.model_validate(await self._block(block_id))

    # ------------------------------------------------------------------ altas

    async def create(self, payload: BlockCreate) -> BlockRead:
        self._assert_own_target(payload.professional_id)
        if payload.ends_at <= _now():
            raise DomainError(422, "block_in_past")
        if payload.professional_id is not None:
            await assert_bookable_resource(
                self.session, self.principal, Professional, payload.professional_id
            )
        if payload.chair_id is not None:
            await assert_bookable_resource(self.session, self.principal, Chair, payload.chair_id)
        block = self._new_block(**payload.model_dump())
        await self.session.flush()
        self._audit_created(block)
        await self.session.commit()
        await self.session.refresh(block)
        return BlockRead.model_validate(block)

    async def create_closure(self, payload: ClosureCreate) -> BlockList:
        """Feriado/cierre: un bloqueo por sillón activo en una única transacción."""
        if payload.ends_at <= _now():
            raise DomainError(422, "block_in_past")
        sillones = (
            (
                await self.session.execute(
                    select(Chair.id)
                    .where(Chair.clinic_id == self.principal.clinic_id, Chair.active.is_(True))
                    .order_by(Chair.created_at, Chair.id)
                )
            )
            .scalars()
            .all()
        )
        if not sillones:
            raise DomainError(422, "no_active_chairs")
        bloques = [
            self._new_block(chair_id=chair_id, professional_id=None, **payload.model_dump())
            for chair_id in sillones
        ]
        await self.session.flush()
        for block in bloques:
            self._audit_created(block)
        await self.session.commit()
        for block in bloques:
            await self.session.refresh(block)
        return BlockList(items=[BlockRead.model_validate(b) for b in bloques])

    # -------------------------------------------------------- edición y retiro

    async def update(self, block_id: uuid.UUID, payload: BlockUpdate) -> BlockRead:
        block = await self._block(block_id)
        ahora = _now()
        valores = payload.model_dump(include=payload.model_fields_set)
        if block.ends_at <= ahora:
            raise DomainError(409, "block_immutable")
        if block.starts_at <= ahora and set(valores) - {"ends_at"}:
            # En curso: el pasado del bloqueo ya ocurrió; solo se mueve el fin.
            raise DomainError(409, "block_immutable")
        nuevo_inicio = valores.get("starts_at", block.starts_at)
        nuevo_fin = valores.get("ends_at", block.ends_at)
        if "starts_at" in valores and nuevo_inicio < ahora:
            raise DomainError(422, "block_in_past")
        if nuevo_fin < ahora:
            raise DomainError(422, "block_in_past")
        if nuevo_fin <= nuevo_inicio:
            raise DomainError(422, "invalid_block_range")

        cambios = apply_changes(block, valores)
        if cambios:
            await self.session.flush()
            record_config_event(
                self.session,
                self.principal,
                entity=ConfigEntity.BLOCK,
                entity_id=block.id,
                action=ConfigAction.UPDATED,
                changes=cambios,
            )
            await self.session.commit()
            await self.session.refresh(block)
        return BlockRead.model_validate(block)

    async def remove(self, block_id: uuid.UUID) -> None:
        """Baja lógica de un bloqueo futuro; uno iniciado o terminado es inmutable."""
        block = await self._block(block_id)
        ahora = _now()
        if block.starts_at <= ahora:
            raise DomainError(409, "block_immutable")
        block.removed_at = ahora
        block.removed_by_user_id = self.principal.user_id
        await self.session.flush()
        record_config_event(
            self.session,
            self.principal,
            entity=ConfigEntity.BLOCK,
            entity_id=block.id,
            action=ConfigAction.REMOVED,
            changes={"removed_at": [None, to_json(ahora)]},
        )
        await self.session.commit()

    # ---------------------------------------------------------------- helpers

    def _assert_own_target(self, professional_id: uuid.UUID | None) -> None:
        """Odontólogo: solo bloquea su propia agenda (matriz RBAC: CR propios)."""
        if self.principal.roles != {UserRole.ODONTOLOGO}:
            return
        if (
            self.principal.professional_id is None
            or professional_id != self.principal.professional_id
        ):
            raise DomainError(403, "forbidden_scope")

    def _new_block(self, **valores: object) -> Block:
        block = Block(
            clinic_id=self.principal.clinic_id,
            created_by_user_id=self.principal.user_id,
            **valores,
        )
        self.session.add(block)
        return block

    def _audit_created(self, block: Block) -> None:
        record_config_event(
            self.session,
            self.principal,
            entity=ConfigEntity.BLOCK,
            entity_id=block.id,
            action=ConfigAction.CREATED,
            changes=snapshot(block, _BLOCK_FIELDS),
        )
