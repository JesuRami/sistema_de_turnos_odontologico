"""Catálogo de plantillas por defecto de cada clínica (C-09, D11).

Datos puros, sin imports del resto de la app: lo usan el seed, el backfill de la migración
`c09_reminder_engine` y los tests, así hay una sola fuente de textos. Los nombres de WhatsApp son
los de la KB (`11_whatsapp_y_recordatorios.md` §2) hasta que Meta apruebe los reales; los de email
son claves internas. Solo variables `{{...}}` del conjunto permitido: ni datos personales ni
`{{direccion}}` (la clínica todavía no guarda dirección; los textos aprobados los define C-10).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

STEP_CREATED = "created"
LOCALE = "es_AR"
ALLOWED_VARIABLES = frozenset({"nombre", "clinica", "fecha", "hora", "profesional", "link"})
_VARIABLE = re.compile(r"\{\{(\w+)\}\}")


@dataclass(frozen=True, slots=True)
class TemplateSpec:
    """Una fila por defecto de `notification_template`."""

    channel: str
    step: str
    meta_template_name: str
    body_preview: str

    @property
    def variables(self) -> frozenset[str]:
        return frozenset(_VARIABLE.findall(self.body_preview))


DEFAULT_TEMPLATES: tuple[TemplateSpec, ...] = (
    TemplateSpec(
        "whatsapp",
        STEP_CREATED,
        "turno_creado_v1",
        "Hola {{nombre}}, tu turno en {{clinica}} es el {{fecha}} a las {{hora}} "
        "con {{profesional}}. Confirmalo acá: {{link}}",
    ),
    TemplateSpec(
        "whatsapp",
        "t_72h",
        "recordatorio_72h_v1",
        "Hola {{nombre}}, te recordamos tu turno del {{fecha}} {{hora}} con "
        "{{profesional}}. ¿Confirmás? {{link}}",
    ),
    TemplateSpec(
        "whatsapp",
        "t_24h",
        "recordatorio_24h_v1",
        "Mañana {{hora}} tenés turno con {{profesional}} en {{clinica}}. Respondé SÍ para "
        "confirmar o tocá para cambiar: {{link}}",
    ),
    TemplateSpec(
        "whatsapp",
        "t_3h",
        "recordatorio_3h_v1",
        "Hoy {{hora}} te esperamos en {{clinica}}. Llegá 10 min antes. {{link}}",
    ),
    TemplateSpec(
        "email",
        STEP_CREATED,
        "email_turno_creado_v1",
        "Hola {{nombre}}, tu turno en {{clinica}} es el {{fecha}} a las {{hora}} con "
        "{{profesional}}. Para confirmarlo o cambiarlo ingresá a {{link}}",
    ),
    TemplateSpec(
        "email",
        "t_72h",
        "email_recordatorio_72h_v1",
        "Hola {{nombre}}, te recordamos tu turno del {{fecha}} a las {{hora}} con "
        "{{profesional}} en {{clinica}}. Confirmalo o cambialo acá: {{link}}",
    ),
    TemplateSpec(
        "email",
        "t_24h",
        "email_recordatorio_24h_v1",
        "Hola {{nombre}}, mañana a las {{hora}} tenés turno con {{profesional}} en "
        "{{clinica}}. Si no podés venir, avisanos acá: {{link}}",
    ),
    TemplateSpec(
        "email",
        "t_3h",
        "email_recordatorio_3h_v1",
        "Hola {{nombre}}, hoy a las {{hora}} te esperamos en {{clinica}} con "
        "{{profesional}}. Llegá 10 minutos antes. Gestioná tu turno: {{link}}",
    ),
)
