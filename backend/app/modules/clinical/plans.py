"""Planes de tratamiento / presupuestos por fases (C-15, D8, spec `clinical/treatment-plans`).

Versiones, ítems y decisiones inmutables. Totales en centavos de ARS calculados acá con enteros
(nunca floats, nunca enviados por el cliente) y acotados al `bigint` de la base. Crear versión y
decidir toman un *advisory lock* por plan (no `FOR UPDATE`: `app_writer` no tiene `UPDATE` en las
tablas append-only, y `SELECT ... FOR UPDATE` lo exige).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import DomainError
from app.common.principal import Principal
from app.models import (
    Clinic,
    ClinicalAction,
    PlanDecision,
    ToothSurface,
    TreatmentPlan,
    TreatmentPlanDecision,
    TreatmentPlanItem,
    TreatmentPlanVersion,
)
from app.modules.clinical.access import RecordRef, resolve_patient, resolve_record
from app.modules.clinical.audit import record_access
from app.modules.clinical.cursor import paginate_desc
from app.modules.clinical.schemas import (
    BIGINT_MAX,
    DecisionCreate,
    DecisionRead,
    PhaseRead,
    PlanCreate,
    PlanDetail,
    PlanItemIn,
    PlanItemRead,
    PlansPage,
    PlanSummary,
    PlanVersionCreate,
    PlanVersionRead,
)

__all__ = ["BIGINT_MAX", "PlanService", "format_ars", "phase_totals"]


def phase_totals(items: Iterable[tuple[int, int, int]]) -> tuple[dict[int, int], int]:
    """`(fase, cantidad, precio)` → subtotales por fase y total; desborde → `422`."""
    fases: dict[int, int] = {}
    total = 0
    for fase, cantidad, precio in items:
        subtotal = cantidad * precio
        total += subtotal
        fases[fase] = fases.get(fase, 0) + subtotal
        if subtotal > BIGINT_MAX or total > BIGINT_MAX:
            raise DomainError(422, "amount_too_large")
    return dict(sorted(fases.items())), total


def format_ars(centavos: int) -> str:
    """`115000` → `1.150,00` (es-AR, sin depender de `locale`)."""
    enteros, resto = divmod(centavos, 100)
    miles = f"{enteros:,}".replace(",", ".")
    return f"{miles},{resto:02d}"


def _validate(items: Sequence[PlanItemIn]) -> None:
    fases = {i.phase for i in items}
    if fases != set(range(1, max(fases) + 1)):
        raise DomainError(422, "invalid_phases")
    phase_totals((i.phase, i.quantity, i.unit_price_cents) for i in items)


def _version_read(version: Any, items: Sequence[Any], decision: Any | None) -> PlanVersionRead:
    por_fase: dict[int, list[PlanItemRead]] = {}
    for it in sorted(items, key=lambda i: i.position):
        por_fase.setdefault(it.phase, []).append(
            PlanItemRead(
                position=it.position,
                phase=it.phase,
                description=it.description,
                quantity=it.quantity,
                unit_price_cents=it.unit_price_cents,
                subtotal_cents=it.quantity * it.unit_price_cents,
                tooth=it.tooth,
                surface=str(it.surface) if it.surface is not None else None,
            )
        )
    subtotales, total = phase_totals((i.phase, i.quantity, i.unit_price_cents) for i in items)
    return PlanVersionRead(
        version=version.version,
        created_at=version.created_at,
        created_by_user_id=version.created_by_user_id,
        phases=[
            PhaseRead(phase=f, subtotal_cents=subtotales[f], items=por_fase[f])
            for f in sorted(por_fase)
        ],
        total_cents=total,
        decision=(
            DecisionRead(
                decision=str(decision.decision),
                note=decision.note,
                decided_by_user_id=decision.decided_by_user_id,
                created_at=decision.created_at,
            )
            if decision is not None
            else None
        ),
    )


class PlanService:
    def __init__(self, session: AsyncSession, principal: Principal) -> None:
        self.session = session
        self.principal = principal

    async def _lock(self, plan_id: uuid.UUID) -> None:
        await self.session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(str(plan_id), 0)))
        )

    async def _plan(self, ficha: RecordRef, plan_id: uuid.UUID) -> TreatmentPlan:
        plan = (
            await self.session.execute(
                select(TreatmentPlan).where(
                    TreatmentPlan.id == plan_id,
                    TreatmentPlan.clinic_id == ficha.clinic_id,
                    TreatmentPlan.record_id == ficha.id,
                )
            )
        ).scalar_one_or_none()
        if plan is None:
            raise DomainError(404, "plan_not_found")
        return plan

    async def _insert_version(
        self, ficha: RecordRef, plan_id: uuid.UUID, numero: int, items: Sequence[PlanItemIn]
    ) -> None:
        version = TreatmentPlanVersion(
            clinic_id=ficha.clinic_id,
            plan_id=plan_id,
            version=numero,
            created_by_user_id=self.principal.user_id,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(version)
                await self.session.flush()
        except IntegrityError:
            raise DomainError(409, "version_conflict") from None
        self.session.add_all(
            [
                TreatmentPlanItem(
                    clinic_id=ficha.clinic_id,
                    version_id=version.id,
                    phase=i.phase,
                    position=n,
                    description=i.description,
                    quantity=i.quantity,
                    unit_price_cents=i.unit_price_cents,
                    tooth=i.tooth,
                    surface=ToothSurface(i.surface) if i.surface else None,
                )
                for n, i in enumerate(items, start=1)
            ]
        )
        await self.session.flush()

    async def _versions(
        self, plan_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, list[PlanVersionRead]]:
        versiones = (
            await self.session.execute(
                select(
                    TreatmentPlanVersion.id,
                    TreatmentPlanVersion.plan_id,
                    TreatmentPlanVersion.version,
                    TreatmentPlanVersion.created_at,
                    TreatmentPlanVersion.created_by_user_id,
                )
                .where(
                    TreatmentPlanVersion.clinic_id == self.principal.clinic_id,
                    TreatmentPlanVersion.plan_id.in_(plan_ids),
                )
                .order_by(TreatmentPlanVersion.version)
            )
        ).all()
        ids = [v.id for v in versiones]
        items = (
            await self.session.execute(
                select(
                    TreatmentPlanItem.version_id,
                    TreatmentPlanItem.position,
                    TreatmentPlanItem.phase,
                    TreatmentPlanItem.description,
                    TreatmentPlanItem.quantity,
                    TreatmentPlanItem.unit_price_cents,
                    TreatmentPlanItem.tooth,
                    TreatmentPlanItem.surface,
                ).where(TreatmentPlanItem.version_id.in_(ids))
            )
        ).all()
        decisiones = {
            d.version_id: d
            for d in (
                await self.session.execute(
                    select(
                        TreatmentPlanDecision.version_id,
                        TreatmentPlanDecision.decision,
                        TreatmentPlanDecision.note,
                        TreatmentPlanDecision.decided_by_user_id,
                        TreatmentPlanDecision.created_at,
                    ).where(TreatmentPlanDecision.version_id.in_(ids))
                )
            ).all()
        }
        por_version: dict[uuid.UUID, list[Any]] = {}
        for it in items:
            por_version.setdefault(it.version_id, []).append(it)
        resultado: dict[uuid.UUID, list[PlanVersionRead]] = {}
        for v in versiones:
            resultado.setdefault(v.plan_id, []).append(
                _version_read(v, por_version.get(v.id, []), decisiones.get(v.id))
            )
        return resultado

    async def _detail(self, plan: TreatmentPlan) -> PlanDetail:
        versiones = (await self._versions([plan.id]))[plan.id]
        return PlanDetail(
            id=plan.id,
            record_id=plan.record_id,
            title=plan.title,
            created_at=plan.created_at,
            latest_version=versiones[-1].version,
            versions=versiones,
        )

    async def create(self, record_id: uuid.UUID, payload: PlanCreate) -> PlanDetail:
        _validate(payload.items)
        ficha = await resolve_record(self.session, self.principal, record_id, write=True)
        plan = TreatmentPlan(
            clinic_id=ficha.clinic_id,
            record_id=ficha.id,
            title=payload.title,
            created_by_user_id=self.principal.user_id,
        )
        self.session.add(plan)
        await self.session.flush()
        await self._insert_version(ficha, plan.id, 1, payload.items)
        await record_access(
            self.session,
            self.principal,
            ficha.id,
            ClinicalAction.PLAN_WRITE,
            object_type="treatment_plan",
            object_id=plan.id,
            payload={"version": 1},
        )
        detalle = await self._detail(plan)
        await self.session.commit()
        return detalle

    async def add_version(
        self, record_id: uuid.UUID, plan_id: uuid.UUID, payload: PlanVersionCreate
    ) -> PlanDetail:
        _validate(payload.items)
        ficha = await resolve_record(self.session, self.principal, record_id, write=True)
        plan = await self._plan(ficha, plan_id)
        await self._lock(plan.id)
        ultima = await self.session.scalar(
            select(func.max(TreatmentPlanVersion.version)).where(
                TreatmentPlanVersion.plan_id == plan.id
            )
        )
        if ultima != payload.expected_version:
            raise DomainError(409, "version_conflict")
        await self._insert_version(ficha, plan.id, payload.expected_version + 1, payload.items)
        await record_access(
            self.session,
            self.principal,
            ficha.id,
            ClinicalAction.PLAN_VERSION_WRITE,
            object_type="treatment_plan",
            object_id=plan.id,
            payload={"version": payload.expected_version + 1},
        )
        detalle = await self._detail(plan)
        await self.session.commit()
        return detalle

    async def decide(
        self, record_id: uuid.UUID, plan_id: uuid.UUID, numero: int, payload: DecisionCreate
    ) -> PlanDetail:
        ficha = await resolve_record(self.session, self.principal, record_id, write=True)
        plan = await self._plan(ficha, plan_id)
        await self._lock(plan.id)
        versiones = (
            await self.session.execute(
                select(TreatmentPlanVersion.id, TreatmentPlanVersion.version).where(
                    TreatmentPlanVersion.plan_id == plan.id
                )
            )
        ).all()
        version = next((v for v in versiones if v.version == numero), None)
        if version is None:
            raise DomainError(404, "version_not_found")
        if numero != max(v.version for v in versiones):
            raise DomainError(409, "version_superseded")
        ya = await self.session.scalar(
            select(TreatmentPlanDecision.id).where(TreatmentPlanDecision.version_id == version.id)
        )
        if ya is not None:
            raise DomainError(409, "version_already_decided")
        try:
            async with self.session.begin_nested():
                self.session.add(
                    TreatmentPlanDecision(
                        clinic_id=ficha.clinic_id,
                        version_id=version.id,
                        decision=PlanDecision(payload.decision),
                        note=payload.note,
                        decided_by_user_id=self.principal.user_id,
                    )
                )
                await self.session.flush()
        except IntegrityError:
            raise DomainError(409, "version_already_decided") from None
        await record_access(
            self.session,
            self.principal,
            ficha.id,
            ClinicalAction.PLAN_DECISION,
            object_type="treatment_plan",
            object_id=plan.id,
            payload={"version": numero, "decision": payload.decision},
        )
        detalle = await self._detail(plan)
        await self.session.commit()
        return detalle

    async def get(self, record_id: uuid.UUID, plan_id: uuid.UUID) -> PlanDetail:
        ficha = await resolve_record(self.session, self.principal, record_id)
        plan = await self._plan(ficha, plan_id)
        detalle = await self._detail(plan)
        await record_access(
            self.session,
            self.principal,
            ficha.id,
            ClinicalAction.PLAN_READ,
            object_type="treatment_plan",
            object_id=plan.id,
        )
        await self.session.commit()
        return detalle

    async def list(self, record_id: uuid.UUID, cursor: str | None, limit: int) -> PlansPage:
        ficha = await resolve_record(self.session, self.principal, record_id)
        stmt = select(TreatmentPlan.id, TreatmentPlan.title, TreatmentPlan.created_at).where(
            TreatmentPlan.clinic_id == ficha.clinic_id, TreatmentPlan.record_id == ficha.id
        )
        filas, siguiente = await paginate_desc(
            self.session, stmt, TreatmentPlan.created_at, TreatmentPlan.id, cursor, limit
        )
        versiones = await self._versions([f.id for f in filas]) if filas else {}
        items = []
        for f in filas:
            ultima = versiones[f.id][-1]
            items.append(
                PlanSummary(
                    id=f.id,
                    title=f.title,
                    created_at=f.created_at,
                    latest_version=ultima.version,
                    total_cents=ultima.total_cents,
                    decision=ultima.decision.decision if ultima.decision else None,
                )
            )
        await record_access(
            self.session,
            self.principal,
            ficha.id,
            ClinicalAction.PLAN_LIST,
            payload={"items": len(items)},
        )
        await self.session.commit()
        return PlansPage(items=items, next_cursor=siguiente)

    async def pdf(
        self, record_id: uuid.UUID, plan_id: uuid.UUID, numero: int, now: datetime
    ) -> bytes:
        from app.modules.clinical.pdf import render_plan_pdf

        ficha = await resolve_record(self.session, self.principal, record_id)
        plan = await self._plan(ficha, plan_id)
        detalle = await self._detail(plan)
        version = next((v for v in detalle.versions if v.version == numero), None)
        if version is None:
            raise DomainError(404, "version_not_found")
        paciente = await resolve_patient(self.session, self.principal, ficha.patient_id)
        clinica = (
            await self.session.execute(
                select(Clinic.name, Clinic.timezone).where(Clinic.id == ficha.clinic_id)
            )
        ).one()
        emitido = now.astimezone(ZoneInfo(clinica.timezone)).date()
        contenido = await asyncio.to_thread(
            render_plan_pdf,
            clinic_name=clinica.name,
            patient_name=paciente.full_name,
            title=plan.title,
            version=version,
            issued_on=emitido,
        )
        await record_access(
            self.session,
            self.principal,
            ficha.id,
            ClinicalAction.PLAN_PDF_EXPORT,
            object_type="treatment_plan",
            object_id=plan.id,
            payload={"version": numero},
        )
        await self.session.commit()
        return contenido
