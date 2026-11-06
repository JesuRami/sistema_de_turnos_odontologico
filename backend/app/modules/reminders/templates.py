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


# Payloads de los botones de respuesta rápida que el webhook interpreta (C-10, D4/D7).
BUTTON_CONFIRM = "confirm"
BUTTON_CHANGE = "change"
BUTTON_CANCEL = "cancel"


@dataclass(frozen=True, slots=True)
class TemplateSpec:
    """Una fila por defecto de `notification_template`.

    Para WhatsApp (C-10) suma lo que la Cloud API necesita y la base no guarda: el orden de los
    parámetros posicionales del cuerpo (`{{1}}`, `{{2}}`…) y los payloads de los botones de
    respuesta rápida, en el orden en que se aprobaron en Meta.
    """

    channel: str
    step: str
    meta_template_name: str
    body_preview: str
    buttons: tuple[str, ...] = ()

    @property
    def variables(self) -> frozenset[str]:
        return frozenset(_VARIABLE.findall(self.body_preview))

    @property
    def param_order(self) -> tuple[str, ...]:
        return param_order_of(self.body_preview)


def param_order_of(body: str) -> tuple[str, ...]:
    """Variables en el orden de su primera aparición en el cuerpo (su posición en Meta)."""
    return tuple(dict.fromkeys(_VARIABLE.findall(body)))


DEFAULT_TEMPLATES: tuple[TemplateSpec, ...] = (
    TemplateSpec(
        "whatsapp",
        STEP_CREATED,
        "turno_creado_v1",
        "Hola {{nombre}}, tu turno en {{clinica}} es el {{fecha}} a las {{hora}} "
        "con {{profesional}}. Confirmalo acá: {{link}}",
        (BUTTON_CONFIRM, BUTTON_CHANGE),
    ),
    TemplateSpec(
        "whatsapp",
        "t_72h",
        "recordatorio_72h_v1",
        "Hola {{nombre}}, te recordamos tu turno del {{fecha}} {{hora}} con "
        "{{profesional}}. ¿Confirmás? {{link}}",
        (BUTTON_CONFIRM, BUTTON_CHANGE),
    ),
    TemplateSpec(
        "whatsapp",
        "t_24h",
        "recordatorio_24h_v1",
        "Mañana {{hora}} tenés turno con {{profesional}} en {{clinica}}. Respondé SÍ para "
        "confirmar o tocá para cambiar: {{link}}",
        (BUTTON_CONFIRM, BUTTON_CHANGE),
    ),
    TemplateSpec(
        "whatsapp",
        "t_3h",
        "recordatorio_3h_v1",
        "Hoy {{hora}} te esperamos en {{clinica}}. Llegá 10 min antes. {{link}}",
        (BUTTON_CANCEL,),
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


def whatsapp_template(meta_template_name: str) -> TemplateSpec:
    """Plantilla de WhatsApp del catálogo por su nombre en Meta; `KeyError` si no existe."""
    for spec in DEFAULT_TEMPLATES:
        if spec.channel == "whatsapp" and spec.meta_template_name == meta_template_name:
            return spec
    raise KeyError(meta_template_name)


def whatsapp_buttons(step: str) -> tuple[str, ...]:
    """Botones de la plantilla de WhatsApp del paso; pasos sin plantilla de catálogo, ninguno."""
    for spec in DEFAULT_TEMPLATES:
        if spec.channel == "whatsapp" and spec.step == step:
            return spec.buttons
    return ()
