"""Ficha clínica y anamnesis versionada (C-15, spec `clinical/patient-record`).

Cada método resuelve el alcance (`access.py`), hace su trabajo, audita en la misma transacción
(`audit.py`) y hace `commit`. Nada se actualiza ni se borra (D1).
"""

from __future__ import annotations

import uuid

from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import DomainError
from app.common.principal import Principal
from app.models import (
    AnamnesisVersion,
    ClinicalAction,
    ClinicalAttachment,
    ClinicalAttachmentRemoval,
    ClinicalEvolution,
    ClinicalRecord,
    TreatmentPlan,
)
from app.modules.clinical.access import resolve_patient, resolve_record
from app.modules.clinical.audit import record_access
from app.modules.clinical.schemas import (
    AnamnesisCreate,
    AnamnesisRead,
    AnamnesisVersionsPage,
    RecordOpened,
    RecordRead,
)

_ANAMNESIS_COLUMNS = (
    AnamnesisVersion.id,
    AnamnesisVersion.version,
    AnamnesisVersion.answers,
    AnamnesisVersion.created_by_user_id,
    AnamnesisVersion.created_at,
)


async def current_anamnesis(
    session: AsyncSession, clinic_id: uuid.UUID, record_id: uuid.UUID
) -> AnamnesisRead | None:
    """La versión vigente es la mayor (nunca una fila mutada)."""
    fila = (
        await session.execute(
            select(*_ANAMNESIS_COLUMNS)
            .where(AnamnesisVersion.clinic_id == clinic_id, AnamnesisVersion.record_id == record_id)
            .order_by(AnamnesisVersion.version.desc())
            .limit(1)
        )
    ).one_or_none()
    return AnamnesisRead.model_validate(fila, from_attributes=True) if fila else None


class RecordService:
    def __init__(self, session: AsyncSession, principal: Principal) -> None:
        self.session = session
        self.principal = principal

    async def open(self, patient_id: uuid.UUID) -> RecordOpened:
        """Idempotente: crea la ficha (`created=True`) o devuelve la existente."""
        paciente = await resolve_patient(self.session, self.principal, patient_id, write=True)
        creada = (
            await self.session.execute(
                pg_insert(ClinicalRecord)
                .values(
                    clinic_id=self.principal.clinic_id,
                    patient_id=paciente.id,
                    created_by_user_id=self.principal.user_id,
                )
                .on_conflict_do_nothing(index_elements=["clinic_id", "patient_id"])
                .returning(ClinicalRecord.id, ClinicalRecord.created_at)
            )
        ).one_or_none()
        fila = (
            creada
            or (
                await self.session.execute(
                    select(ClinicalRecord.id, ClinicalRecord.created_at).where(
                        ClinicalRecord.clinic_id == self.principal.clinic_id,
                        ClinicalRecord.patient_id == paciente.id,
                    )
                )
            ).one()
        )
        await record_access(
            self.session,
            self.principal,
            fila.id,
            ClinicalAction.RECORD_OPEN if creada else ClinicalAction.RECORD_READ,
            object_type="clinical_record",
            object_id=fila.id,
        )
        await self.session.commit()
        return RecordOpened(
            record_id=fila.id,
            patient_id=paciente.id,
            created_at=fila.created_at,
            created=creada is not None,
        )

    async def get(self, patient_id: uuid.UUID) -> RecordRead:
        paciente = await resolve_patient(self.session, self.principal, patient_id)
        clinica = self.principal.clinic_id
        fila = (
            await self.session.execute(
                select(ClinicalRecord.id, ClinicalRecord.created_at).where(
                    ClinicalRecord.clinic_id == clinica, ClinicalRecord.patient_id == paciente.id
                )
            )
        ).one_or_none()
        if fila is None:
            raise DomainError(404, "clinical_record_not_opened")
        evoluciones = await self.session.scalar(
            select(func.count(ClinicalEvolution.id)).where(
                ClinicalEvolution.clinic_id == clinica, ClinicalEvolution.record_id == fila.id
            )
        )
        adjuntos = await self.session.scalar(
            select(func.count(ClinicalAttachment.id)).where(
                ClinicalAttachment.clinic_id == clinica,
                ClinicalAttachment.record_id == fila.id,
                ~exists().where(ClinicalAttachmentRemoval.attachment_id == ClinicalAttachment.id),
            )
        )
        planes = await self.session.scalar(
            select(func.count(TreatmentPlan.id)).where(
                TreatmentPlan.clinic_id == clinica, TreatmentPlan.record_id == fila.id
            )
        )
        anamnesis = await current_anamnesis(self.session, clinica, fila.id)
        await record_access(
            self.session,
            self.principal,
            fila.id,
            ClinicalAction.RECORD_READ,
            object_type="clinical_record",
            object_id=fila.id,
        )
        await self.session.commit()
        return RecordRead(
            record_id=fila.id,
            patient_id=paciente.id,
            patient_name=paciente.full_name,
            patient_archived=paciente.archived,
            created_at=fila.created_at,
            anamnesis=anamnesis,
            evolutions_count=int(evoluciones or 0),
            attachments_count=int(adjuntos or 0),
            plans_count=int(planes or 0),
        )


class AnamnesisService:
    """Anamnesis N+1 con control optimista (`expected_version`); nunca se reescribe."""

    def __init__(self, session: AsyncSession, principal: Principal) -> None:
        self.session = session
        self.principal = principal

    async def create(self, record_id: uuid.UUID, payload: AnamnesisCreate) -> AnamnesisRead:
        ficha = await resolve_record(self.session, self.principal, record_id, write=True)
        ultima = await self.session.scalar(
            select(func.max(AnamnesisVersion.version)).where(
                AnamnesisVersion.clinic_id == ficha.clinic_id,
                AnamnesisVersion.record_id == ficha.id,
            )
        )
        if (ultima or 0) != payload.expected_version:
            raise DomainError(409, "version_conflict")
        version = AnamnesisVersion(
            clinic_id=ficha.clinic_id,
            record_id=ficha.id,
            version=payload.expected_version + 1,
            answers=payload.answers.model_dump(mode="json"),
            created_by_user_id=self.principal.user_id,
        )
        try:
            # Una carrera con el mismo `expected_version` choca con UNIQUE (record_id, version).
            async with self.session.begin_nested():
                self.session.add(version)
                await self.session.flush()
        except IntegrityError:
            raise DomainError(409, "version_conflict") from None
        await record_access(
            self.session,
            self.principal,
            ficha.id,
            ClinicalAction.ANAMNESIS_WRITE,
            object_type="anamnesis_version",
            object_id=version.id,
            payload={"version": version.version},
        )
        await self.session.commit()
        return AnamnesisRead.model_validate(version, from_attributes=True)

    async def current(self, record_id: uuid.UUID) -> AnamnesisRead | None:
        ficha = await resolve_record(self.session, self.principal, record_id)
        vigente = await current_anamnesis(self.session, ficha.clinic_id, ficha.id)
        await record_access(
            self.session,
            self.principal,
            ficha.id,
            ClinicalAction.ANAMNESIS_READ,
            payload={"version": vigente.version if vigente else 0},
        )
        await self.session.commit()
        return vigente

    async def versions(
        self, record_id: uuid.UUID, before_version: int | None, limit: int
    ) -> AnamnesisVersionsPage:
        """Todas las versiones, la más nueva primero (cursor = número de versión)."""
        ficha = await resolve_record(self.session, self.principal, record_id)
        stmt = select(*_ANAMNESIS_COLUMNS).where(
            AnamnesisVersion.clinic_id == ficha.clinic_id, AnamnesisVersion.record_id == ficha.id
        )
        if before_version is not None:
            stmt = stmt.where(AnamnesisVersion.version < before_version)
        filas = (
            await self.session.execute(
                stmt.order_by(AnamnesisVersion.version.desc()).limit(limit + 1)
            )
        ).all()
        pagina = filas[:limit]
        await record_access(
            self.session,
            self.principal,
            ficha.id,
            ClinicalAction.ANAMNESIS_READ,
            payload={"versions": len(pagina)},
        )
        await self.session.commit()
        return AnamnesisVersionsPage(
            items=[AnamnesisRead.model_validate(f, from_attributes=True) for f in pagina],
            next_cursor=pagina[-1].version if len(filas) > limit else None,
        )
