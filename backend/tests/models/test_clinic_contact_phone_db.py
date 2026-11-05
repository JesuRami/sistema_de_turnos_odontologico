"""Invariantes de base de `clinic.contact_phone` (C-08, D12).

La base defiende sola el largo del teléfono de contacto: `NULL` (clínica sin
teléfono) o un E.164 de 11 a 32 caracteres. El modelo y la migración no pueden
divergir (regla dura 3).
"""

from __future__ import annotations

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from app.models import Base, Clinic
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db_utils import alembic_config, fetch_rows
from tests.factories import unique_slug

pytestmark = pytest.mark.integration


async def test_contact_phone_null_es_valido(db_session: AsyncSession) -> None:
    clinic = Clinic(name="Clínica Ficticia Sin Teléfono", slug=unique_slug())
    db_session.add(clinic)
    await db_session.flush()
    await db_session.refresh(clinic)

    assert clinic.contact_phone is None


async def test_contact_phone_e164_de_trece_caracteres_es_valido(db_session: AsyncSession) -> None:
    clinic = Clinic(
        name="Clínica Ficticia Con Teléfono",
        slug=unique_slug(),
        contact_phone="+541155550100",
    )
    db_session.add(clinic)
    await db_session.flush()
    await db_session.refresh(clinic)

    assert clinic.contact_phone == "+541155550100"


@pytest.mark.parametrize(
    "valor",
    [
        pytest.param("+1234", id="cinco-caracteres"),
        pytest.param("+" + "1" * 32, id="treinta-y-tres-caracteres"),
    ],
)
async def test_contact_phone_fuera_de_rango_viola_el_check(
    db_session: AsyncSession, valor: str
) -> None:
    db_session.add(Clinic(name="Clínica Ficticia", slug=unique_slug(), contact_phone=valor))
    with pytest.raises(IntegrityError, match="ck_clinic_contact_phone_length"):
        await db_session.flush()


def test_migracion_crea_la_columna_y_el_check_validado(temp_database: str) -> None:
    command.upgrade(alembic_config(), "head")

    columnas = {
        str(r[0]): bool(r[1])
        for r in fetch_rows(
            "SELECT column_name, is_nullable FROM information_schema.columns "
            "WHERE table_name = 'clinic' AND column_name = 'contact_phone'",
            temp_database,
        )
    }
    assert columnas == {"contact_phone": True}
    restricciones = {
        str(r[0]): bool(r[1])
        for r in fetch_rows(
            "SELECT conname, convalidated FROM pg_constraint "
            "WHERE conrelid = 'clinic'::regclass AND conname = 'ck_clinic_contact_phone_length'",
            temp_database,
        )
    }
    assert restricciones == {"ck_clinic_contact_phone_length": True}


def test_modelos_y_migracion_no_divergen_en_contact_phone(temp_database: str) -> None:
    """Autogenerate contra la DB migrada no propone cambios (regla dura 3)."""
    import asyncio
    import os

    from app.core.database import async_database_url
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    command.upgrade(alembic_config(), "head")

    async def _diff() -> list[object]:
        engine = create_async_engine(
            async_database_url(os.environ["DATABASE_URL"]), poolclass=NullPool
        )
        try:
            async with engine.connect() as conn:

                def _compare(sync_conn: object) -> list[object]:
                    ctx = MigrationContext.configure(sync_conn)  # type: ignore[arg-type]
                    return list(compare_metadata(ctx, Base.metadata))

                return await conn.run_sync(_compare)
        finally:
            await engine.dispose()

    assert asyncio.run(_diff()) == []
