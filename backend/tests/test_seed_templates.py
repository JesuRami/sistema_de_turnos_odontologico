"""El seed crea las plantillas por defecto de cada clínica sin pisar las editadas.

C-09 (D11): alta + 72/24/3 h por canal. C-12 (D2): suma la oferta de la lista de espera.
"""

import pytest
from app.models import NotificationTemplate, ReminderChannel
from app.modules.reminders.templates import ALLOWED_VARIABLES, DEFAULT_TEMPLATES, LOCALE
from app.seed import SeedConfig, seed_clinic
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

CLAVE = "clave-seed-de-prueba-no-real-7"


def _config(slug: str) -> SeedConfig:
    return SeedConfig(
        clinic_slug=slug,
        clinic_name="Clínica Seed Ficticia",
        admin_email="admin@example.com",
        admin_password=CLAVE,
    )


async def _plantillas(session: AsyncSession) -> list[NotificationTemplate]:
    return list(
        (
            await session.execute(
                select(NotificationTemplate)
                .order_by(NotificationTemplate.channel, NotificationTemplate.step)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )


async def test_el_seed_crea_diez_plantillas_activas_cinco_por_canal(
    db_session: AsyncSession,
) -> None:
    await seed_clinic(db_session, _config("clinica-plantillas-1"))

    plantillas = await _plantillas(db_session)
    assert len(plantillas) == 10
    assert {p.channel for p in plantillas} == {ReminderChannel.WHATSAPP, ReminderChannel.EMAIL}
    for canal in ReminderChannel:
        pasos = sorted(p.step for p in plantillas if p.channel is canal)
        assert pasos == ["created", "t_24h", "t_3h", "t_72h", "waitlist_offer"]
    assert all(p.active and p.locale == LOCALE for p in plantillas)
    nombres = {p.meta_template_name for p in plantillas if p.channel is ReminderChannel.WHATSAPP}
    assert nombres == {
        "turno_creado_v1",
        "recordatorio_72h_v1",
        "recordatorio_24h_v1",
        "recordatorio_3h_v1",
        "hueco_lista_espera_v1",
    }


async def test_reejecutar_no_duplica_ni_pisa_un_texto_editado(db_session: AsyncSession) -> None:
    await seed_clinic(db_session, _config("clinica-plantillas-2"))
    await db_session.execute(
        update(NotificationTemplate)
        .where(NotificationTemplate.step == "t_24h", NotificationTemplate.channel == "whatsapp")
        .values(body_preview="Texto editado por el admin {{link}}", active=False)
    )

    await seed_clinic(db_session, _config("clinica-plantillas-2"))

    plantillas = await _plantillas(db_session)
    assert len(plantillas) == 10
    editada = next(
        p for p in plantillas if p.step == "t_24h" and p.channel is ReminderChannel.WHATSAPP
    )
    assert editada.body_preview == "Texto editado por el admin {{link}}"
    assert editada.active is False


async def test_reejecutar_repone_la_plantilla_que_falte(db_session: AsyncSession) -> None:
    await seed_clinic(db_session, _config("clinica-plantillas-3"))
    await db_session.execute(
        delete(NotificationTemplate).where(NotificationTemplate.step == "t_3h")
    )

    await seed_clinic(db_session, _config("clinica-plantillas-3"))

    assert await db_session.scalar(select(func.count()).select_from(NotificationTemplate)) == 10


def test_catalogo_solo_usa_variables_permitidas_y_sin_datos_reales() -> None:
    assert len(DEFAULT_TEMPLATES) == 10
    for spec in DEFAULT_TEMPLATES:
        assert spec.variables <= ALLOWED_VARIABLES, spec.meta_template_name
        assert "{{direccion}}" not in spec.body_preview
        assert "{{link}}" in spec.body_preview
        assert "@" not in spec.body_preview and "+54" not in spec.body_preview
        assert spec.body_preview.strip()


async def test_clinica_existente_recibe_las_plantillas_de_oferta(db_session: AsyncSession) -> None:
    """Re-ejecutar el seed sobre una clínica previa a C-12 agrega solo las dos de oferta."""
    await seed_clinic(db_session, _config("clinica-plantillas-4"))
    await db_session.execute(
        update(NotificationTemplate)
        .where(NotificationTemplate.step == "t_24h", NotificationTemplate.channel == "email")
        .values(body_preview="Texto propio {{link}}")
    )
    await db_session.execute(
        delete(NotificationTemplate).where(NotificationTemplate.step == "waitlist_offer")
    )
    antes = {(p.channel, p.step): p.body_preview for p in await _plantillas(db_session)}
    assert len(antes) == 8

    await seed_clinic(db_session, _config("clinica-plantillas-4"))

    despues = {(p.channel, p.step): p.body_preview for p in await _plantillas(db_session)}
    assert len(despues) == 10
    assert {k: v for k, v in despues.items() if k in antes} == antes
    assert {k[1] for k in despues.keys() - antes.keys()} == {"waitlist_offer"}
