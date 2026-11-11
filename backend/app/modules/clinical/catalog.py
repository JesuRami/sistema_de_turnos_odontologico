"""Catálogos clínicos iniciales (C-15, Decisiones 8 y 9) — PROVISIONALES.

Pendiente de validación por un odontólogo de la clínica piloto (task 0.3): por eso viven como
**datos** en este único archivo (sin lógica), para cambiarlos sin tocar servicios ni migración.

- `INITIAL_CONDITIONS`: estados del odontograma sembrados por clínica (la migración y el seed
  insertan con `ON CONFLICT DO NOTHING`: nunca pisan un estado existente).
- `SYSTEMIC_CONDITIONS`: casilleros de "condiciones sistémicas" de la anamnesis.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.odontogram_condition import OdontogramCondition

ConditionScope = Literal["surface", "tooth"]


@dataclass(frozen=True, slots=True)
class ConditionSpec:
    code: str
    label: str
    category: str
    scope: ConditionScope


INITIAL_CONDITIONS: tuple[ConditionSpec, ...] = (
    ConditionSpec("sano", "Sano", "estado", "tooth"),
    ConditionSpec("caries", "Caries", "patologia", "surface"),
    ConditionSpec("obturacion", "Obturación", "restauracion", "surface"),
    ConditionSpec("sellador", "Sellador", "restauracion", "surface"),
    ConditionSpec("corona", "Corona", "protesis", "tooth"),
    ConditionSpec("protesis_fija", "Prótesis fija", "protesis", "tooth"),
    ConditionSpec("endodoncia", "Endodoncia", "tratamiento", "tooth"),
    ConditionSpec("implante", "Implante", "protesis", "tooth"),
    ConditionSpec("fractura", "Fractura", "patologia", "tooth"),
    ConditionSpec("extraccion_indicada", "Extracción indicada", "indicacion", "tooth"),
    ConditionSpec("ausente", "Ausente", "ausencia", "tooth"),
)

SYSTEMIC_CONDITIONS: tuple[tuple[str, str], ...] = (
    ("hipertension", "Hipertensión"),
    ("diabetes", "Diabetes"),
    ("cardiopatia", "Cardiopatía"),
    ("asma", "Asma"),
    ("hepatitis", "Hepatitis"),
    ("vih", "VIH"),
    ("trastorno_coagulacion", "Trastorno de la coagulación"),
    ("enfermedad_renal", "Enfermedad renal"),
    ("epilepsia", "Epilepsia"),
    ("tiroides", "Trastorno tiroideo"),
)
SYSTEMIC_CONDITION_CODES = frozenset(code for code, _ in SYSTEMIC_CONDITIONS)

# SQL de siembra del catálogo para una clínica (`:clinic_id`) o para todas (`clinic_ids` = NULL).
SEED_CONDITIONS_SQL = (
    "INSERT INTO odontogram_condition (clinic_id, code, label, category, scope) "
    "SELECT c.id, :code, :label, :category, :scope FROM clinic c "
    "WHERE (CAST(:clinic_id AS uuid) IS NULL OR c.id = CAST(:clinic_id AS uuid)) "
    "ON CONFLICT (clinic_id, code) DO NOTHING"
)


async def seed_clinical_catalog(session: AsyncSession, clinic_id: uuid.UUID) -> None:
    """Inserta los estados iniciales que la clínica todavía no tenga (no pisa ni reactiva)."""
    await session.execute(
        pg_insert(OdontogramCondition)
        .values(
            [
                {
                    "clinic_id": clinic_id,
                    "code": spec.code,
                    "label": spec.label,
                    "category": spec.category,
                    "scope": spec.scope,
                }
                for spec in INITIAL_CONDITIONS
            ]
        )
        .on_conflict_do_nothing(index_elements=["clinic_id", "code"])
    )
