"""Piezas compartidas por los modelos clínicos de C-15 (D1, D2).

- `fdi_tooth_sql`: numeración FDI válida (permanentes 11–48, temporales 51–85). La misma regla
  vive en `app.modules.clinical.fdi` para validar en el borde; la base es la última barrera.
- Enums nativos de Postgres creados por la migración `c15_clinical_record`.
"""

from app.models.appointment import pg_enum
from app.models.enums import (
    AttachmentKind,
    ClinicalAction,
    EvolutionKind,
    PlanDecision,
    ToothSurface,
)


def fdi_tooth_sql(column: str) -> str:
    """CHECK de pieza FDI sobre `column` (cuadrante 1–4: piezas 1–8; 5–8: piezas 1–5)."""
    return (
        f"({column} / 10 BETWEEN 1 AND 4 AND {column} % 10 BETWEEN 1 AND 8) "
        f"OR ({column} / 10 BETWEEN 5 AND 8 AND {column} % 10 BETWEEN 1 AND 5)"
    )


TOOTH_SURFACE = pg_enum(ToothSurface, "tooth_surface")
EVOLUTION_KIND = pg_enum(EvolutionKind, "evolution_kind")
ATTACHMENT_KIND = pg_enum(AttachmentKind, "attachment_kind")
PLAN_DECISION = pg_enum(PlanDecision, "plan_decision")
CLINICAL_ACTION = pg_enum(ClinicalAction, "clinical_action")

# Payload de auditoría sin texto libre: valores escalares; los strings solo como ids o códigos
# cortos en minúscula (uuid, `permanent`, `xray`...). Nunca objetos ni listas anidadas.
ACCESS_PAYLOAD_SAFE_SQL = (
    "jsonb_typeof(payload) = 'object' AND NOT jsonb_path_exists(payload, "
    '\'$.* ? (@.type() == "object" || @.type() == "array" '
    '|| (@.type() == "string" && !(@ like_regex "^[0-9a-z_-]{1,64}$")))\')'
)
