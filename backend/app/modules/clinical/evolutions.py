"""Evoluciones clínicas (C-15, D6, spec `clinical/evolutions`).

Firma **simple** (no Ley 25.506): `professional_id` del principal + `signed_at` del reloj del
servidor (`app.common.clock`) + `content_sha256` del contenido canónico, verificable offline:

    sha256(json.dumps({record_id, appointment_id, professional_id, kind, corrects_evolution_id,
                       reason, body, signed_at}, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8"))

con ids como texto, `null` para lo ausente y `signed_at` en UTC ISO-8601 con microsegundos.

Una corrección es una fila nueva que referencia a la evolución corregida **más reciente** de la
cadena (lineal), así el listado marca `corrected_by` sin recorrer grafos. Solo el autor
(`professional_id`) corrige (Decisión 4). Nada se reescribe.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import DomainError
from app.common.principal import Principal
from app.models import (
    Appointment,
    ClinicalAction,
    ClinicalEvolution,
    EvolutionKind,
    UserRole,
)
from app.modules.clinical.access import RecordRef, resolve_record
from app.modules.clinical.audit import record_access
from app.modules.clinical.cursor import paginate_desc
from app.modules.clinical.schemas import (
    CorrectionCreate,
    EvolutionCreate,
    EvolutionRead,
    EvolutionsPage,
)

_COLUMNS = (
    ClinicalEvolution.id,
    ClinicalEvolution.record_id,
    ClinicalEvolution.kind,
    ClinicalEvolution.body,
    ClinicalEvolution.appointment_id,
    ClinicalEvolution.professional_id,
    ClinicalEvolution.created_by_user_id,
    ClinicalEvolution.signed_at,
    ClinicalEvolution.content_sha256,
    ClinicalEvolution.corrects_evolution_id,
    ClinicalEvolution.reason,
)


def _text(valor: uuid.UUID | None) -> str | None:
    return str(valor) if valor is not None else None


def evolution_hash(
    *,
    record_id: uuid.UUID,
    appointment_id: uuid.UUID | None,
    professional_id: uuid.UUID,
    kind: EvolutionKind,
    corrects_evolution_id: uuid.UUID | None,
    reason: str | None,
    body: str,
    signed_at: datetime,
) -> str:
    """SHA-256 hex del contenido canónico (ver docstring del módulo)."""
    canonico = {
        "record_id": str(record_id),
        "appointment_id": _text(appointment_id),
        "professional_id": str(professional_id),
        "kind": kind.value,
        "corrects_evolution_id": _text(corrects_evolution_id),
        "reason": reason,
        "body": body,
        "signed_at": signed_at.astimezone(UTC).isoformat(timespec="microseconds"),
    }
    crudo = json.dumps(canonico, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(crudo.encode("utf-8")).hexdigest()


def _read(
    fila: Row[Any] | ClinicalEvolution, corrected_by: uuid.UUID | None = None
) -> EvolutionRead:
    return EvolutionRead(
        id=fila.id,
        record_id=fila.record_id,
        kind=fila.kind,
        body=fila.body,
        appointment_id=fila.appointment_id,
        professional_id=fila.professional_id,
        created_by_user_id=fila.created_by_user_id,
        signed_at=fila.signed_at,
        content_sha256=fila.content_sha256,
        corrects_evolution_id=fila.corrects_evolution_id,
        reason=fila.reason,
        corrected_by=corrected_by,
    )


class EvolutionService:
    def __init__(self, session: AsyncSession, principal: Principal, now: datetime) -> None:
        self.session = session
        self.principal = principal
        self.now = now

    async def _check_appointment(self, ficha: RecordRef, appointment_id: uuid.UUID) -> None:
        """Mismo paciente y clínica; para el odontólogo, además su propio turno."""
        stmt = select(Appointment.id).where(
            Appointment.id == appointment_id,
            Appointment.clinic_id == ficha.clinic_id,
            Appointment.patient_id == ficha.patient_id,
        )
        if self.principal.roles == {UserRole.ODONTOLOGO}:
            stmt = stmt.where(Appointment.professional_id == self.principal.professional_id)
        if (await self.session.execute(stmt)).one_or_none() is None:
            raise DomainError(422, "appointment_mismatch")

    async def _insert(
        self,
        ficha: RecordRef,
        *,
        body: str,
        appointment_id: uuid.UUID | None,
        kind: EvolutionKind,
        corrects: uuid.UUID | None = None,
        reason: str | None = None,
    ) -> ClinicalEvolution:
        professional_id = self.principal.professional_id
        assert professional_id is not None  # garantizado por ClinicalWriter
        evolucion = ClinicalEvolution(
            id=uuid.uuid4(),
            clinic_id=ficha.clinic_id,
            record_id=ficha.id,
            appointment_id=appointment_id,
            professional_id=professional_id,
            created_by_user_id=self.principal.user_id,
            kind=kind,
            corrects_evolution_id=corrects,
            reason=reason,
            body=body,
            signed_at=self.now,
            content_sha256=evolution_hash(
                record_id=ficha.id,
                appointment_id=appointment_id,
                professional_id=professional_id,
                kind=kind,
                corrects_evolution_id=corrects,
                reason=reason,
                body=body,
                signed_at=self.now,
            ),
        )
        self.session.add(evolucion)
        await self.session.flush()
        return evolucion

    async def create(self, record_id: uuid.UUID, payload: EvolutionCreate) -> EvolutionRead:
        ficha = await resolve_record(self.session, self.principal, record_id, write=True)
        if payload.appointment_id is not None:
            await self._check_appointment(ficha, payload.appointment_id)
        evolucion = await self._insert(
            ficha,
            body=payload.body,
            appointment_id=payload.appointment_id,
            kind=EvolutionKind.ENTRY,
        )
        await record_access(
            self.session,
            self.principal,
            ficha.id,
            ClinicalAction.EVOLUTION_WRITE,
            object_type="clinical_evolution",
            object_id=evolucion.id,
        )
        await self.session.commit()
        return _read(evolucion)

    async def _latest_in_chain(self, ficha: RecordRef, evolution_id: uuid.UUID) -> uuid.UUID:
        """Sigue las correcciones hasta la más reciente (cadena lineal, D6)."""
        actual = evolution_id
        while True:
            siguiente = await self.session.scalar(
                select(ClinicalEvolution.id)
                .where(
                    ClinicalEvolution.clinic_id == ficha.clinic_id,
                    ClinicalEvolution.record_id == ficha.id,
                    ClinicalEvolution.corrects_evolution_id == actual,
                )
                .order_by(ClinicalEvolution.signed_at.desc(), ClinicalEvolution.id.desc())
                .limit(1)
            )
            if siguiente is None:
                return actual
            actual = siguiente

    async def correct(
        self, record_id: uuid.UUID, evolution_id: uuid.UUID, payload: CorrectionCreate
    ) -> EvolutionRead:
        ficha = await resolve_record(self.session, self.principal, record_id, write=True)
        original = (
            await self.session.execute(
                select(ClinicalEvolution.professional_id, ClinicalEvolution.appointment_id).where(
                    ClinicalEvolution.id == evolution_id,
                    ClinicalEvolution.clinic_id == ficha.clinic_id,
                    ClinicalEvolution.record_id == ficha.id,
                )
            )
        ).one_or_none()
        if original is None:
            raise DomainError(404, "evolution_not_found")
        if original.professional_id != self.principal.professional_id:
            raise DomainError(403, "not_evolution_author")
        destino = await self._latest_in_chain(ficha, evolution_id)
        correccion = await self._insert(
            ficha,
            body=payload.body,
            appointment_id=original.appointment_id,
            kind=EvolutionKind.CORRECTION,
            corrects=destino,
            reason=payload.reason,
        )
        await record_access(
            self.session,
            self.principal,
            ficha.id,
            ClinicalAction.EVOLUTION_CORRECT,
            object_type="clinical_evolution",
            object_id=correccion.id,
            payload={"corrects": destino},
        )
        await self.session.commit()
        return _read(correccion)

    async def list(
        self,
        record_id: uuid.UUID,
        appointment_id: uuid.UUID | None,
        cursor: str | None,
        limit: int,
    ) -> EvolutionsPage:
        ficha = await resolve_record(self.session, self.principal, record_id)
        stmt = select(*_COLUMNS).where(
            ClinicalEvolution.clinic_id == ficha.clinic_id, ClinicalEvolution.record_id == ficha.id
        )
        if appointment_id is not None:
            stmt = stmt.where(ClinicalEvolution.appointment_id == appointment_id)
        filas, siguiente = await paginate_desc(
            self.session, stmt, ClinicalEvolution.signed_at, ClinicalEvolution.id, cursor, limit
        )
        correcciones: dict[uuid.UUID, uuid.UUID] = {}
        if filas:
            marcas = (
                await self.session.execute(
                    select(ClinicalEvolution.corrects_evolution_id, ClinicalEvolution.id)
                    .where(
                        ClinicalEvolution.clinic_id == ficha.clinic_id,
                        ClinicalEvolution.corrects_evolution_id.in_([f.id for f in filas]),
                    )
                    .order_by(ClinicalEvolution.signed_at.desc(), ClinicalEvolution.id.desc())
                )
            ).all()
            for corregida, correccion in marcas:
                correcciones.setdefault(corregida, correccion)
        await record_access(
            self.session,
            self.principal,
            ficha.id,
            ClinicalAction.EVOLUTION_READ,
            payload={"items": len(filas)},
        )
        await self.session.commit()
        return EvolutionsPage(
            items=[_read(f, correcciones.get(f.id)) for f in filas], next_cursor=siguiente
        )
