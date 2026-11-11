"""El seed siembra el catálogo inicial del odontograma por clínica (C-15, Decisión 8).

Escenarios "Catálogo sembrado" y "Catálogo aislado": idempotente (no pisa un estado
desactivado) y cada clínica tiene su propia copia. Datos sintéticos.
"""

import pytest
from app.models import Clinic, OdontogramCondition
from app.modules.clinical.catalog import INITIAL_CONDITIONS
from app.seed import SeedConfig, seed_clinic
from sqlalchemy import select, update
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


async def _catalogo(session: AsyncSession, slug: str) -> dict[str, tuple[str, bool]]:
    filas = (
        await session.execute(
            select(OdontogramCondition.code, OdontogramCondition.scope, OdontogramCondition.active)
            .join(Clinic, Clinic.id == OdontogramCondition.clinic_id)
            .where(Clinic.slug == slug)
            .execution_options(populate_existing=True)
        )
    ).all()
    return {f.code: (f.scope, f.active) for f in filas}


async def test_el_seed_crea_el_catalogo_inicial(db_session: AsyncSession) -> None:
    await seed_clinic(db_session, _config("clinica-catalogo-1"))

    catalogo = await _catalogo(db_session, "clinica-catalogo-1")
    assert len(catalogo) == 11
    assert catalogo["caries"] == ("surface", True)
    assert catalogo["ausente"] == ("tooth", True)


async def test_el_seed_es_idempotente_y_no_reactiva(db_session: AsyncSession) -> None:
    await seed_clinic(db_session, _config("clinica-catalogo-2"))
    clinica = await db_session.scalar(select(Clinic.id).where(Clinic.slug == "clinica-catalogo-2"))
    await db_session.execute(
        update(OdontogramCondition)
        .where(OdontogramCondition.clinic_id == clinica, OdontogramCondition.code == "sellador")
        .values(active=False)
    )

    await seed_clinic(db_session, _config("clinica-catalogo-2"))

    catalogo = await _catalogo(db_session, "clinica-catalogo-2")
    assert len(catalogo) == len(INITIAL_CONDITIONS)
    assert catalogo["sellador"] == ("surface", False)


async def test_el_catalogo_es_por_clinica(db_session: AsyncSession) -> None:
    await seed_clinic(db_session, _config("clinica-catalogo-a"))
    await seed_clinic(db_session, _config("clinica-catalogo-b"))
    ids_a = set(
        (
            await db_session.execute(
                select(OdontogramCondition.id)
                .join(Clinic, Clinic.id == OdontogramCondition.clinic_id)
                .where(Clinic.slug == "clinica-catalogo-a")
            )
        ).scalars()
    )
    ids_b = set(
        (
            await db_session.execute(
                select(OdontogramCondition.id)
                .join(Clinic, Clinic.id == OdontogramCondition.clinic_id)
                .where(Clinic.slug == "clinica-catalogo-b")
            )
        ).scalars()
    )

    assert len(ids_a) == len(ids_b) == 11
    assert ids_a.isdisjoint(ids_b)
