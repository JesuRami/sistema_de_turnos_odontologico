"""Catálogo de plantillas de WhatsApp para la Cloud API (C-10, D4; spec whatsapp-channel).

Meta recibe los parámetros del cuerpo de forma posicional (`{{1}}`, `{{2}}`…) y los botones de
respuesta rápida en un orden fijo: el catálogo declara ambos por plantilla, así el adaptador no
adivina y el README de alta en Meta puede copiarse del mismo dato.
"""

import pytest
from app.modules.reminders.templates import DEFAULT_TEMPLATES, TemplateSpec

WHATSAPP = [t for t in DEFAULT_TEMPLATES if t.channel == "whatsapp"]
EMAIL = [t for t in DEFAULT_TEMPLATES if t.channel == "email"]
BOTONES_ESPERADOS = {
    "created": ("confirm", "change"),
    "t_72h": ("confirm", "change"),
    "t_24h": ("confirm", "change"),
    "t_3h": ("cancel",),
}


def test_hay_una_plantilla_de_whatsapp_por_paso() -> None:
    assert sorted(t.step for t in WHATSAPP) == sorted(BOTONES_ESPERADOS)


@pytest.mark.parametrize("spec", WHATSAPP, ids=lambda s: s.meta_template_name)
def test_param_order_cubre_exactamente_las_variables(spec: TemplateSpec) -> None:
    assert len(spec.param_order) == len(set(spec.param_order))
    assert set(spec.param_order) == spec.variables


@pytest.mark.parametrize("spec", WHATSAPP, ids=lambda s: s.meta_template_name)
def test_param_order_sigue_el_orden_del_cuerpo(spec: TemplateSpec) -> None:
    posiciones = [spec.body_preview.index("{{" + v + "}}") for v in spec.param_order]
    assert posiciones == sorted(posiciones)


@pytest.mark.parametrize("spec", WHATSAPP, ids=lambda s: s.meta_template_name)
def test_botones_por_paso(spec: TemplateSpec) -> None:
    assert spec.buttons == BOTONES_ESPERADOS[spec.step]


@pytest.mark.parametrize("spec", EMAIL, ids=lambda s: s.meta_template_name)
def test_el_email_no_lleva_botones(spec: TemplateSpec) -> None:
    assert spec.buttons == ()


def test_busqueda_por_nombre_de_meta() -> None:
    from app.modules.reminders.templates import whatsapp_template

    assert whatsapp_template("recordatorio_24h_v1").step == "t_24h"
    with pytest.raises(KeyError):
        whatsapp_template("inexistente_v1")
