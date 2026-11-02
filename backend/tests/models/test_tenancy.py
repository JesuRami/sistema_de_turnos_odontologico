"""Invariante estructural de tenancy (regla 4): toda tabla operativa lleva clinic_id NOT NULL."""

import pytest
from app.models import Base
from sqlalchemy import Table, text
from sqlalchemy.ext.asyncio import AsyncSession

OPERATIVAS = sorted(name for name in Base.metadata.tables if name != "clinic")


def test_hay_tablas_operativas_que_verificar() -> None:
    assert {"professional", "chair", "schedule_rule", "patient", "user"} <= set(OPERATIVAS)


@pytest.mark.parametrize("nombre", OPERATIVAS)
def test_modelo_declara_clinic_id_obligatorio_con_fk_a_clinic(nombre: str) -> None:
    tabla: Table = Base.metadata.tables[nombre]
    columna = tabla.c.clinic_id
    assert columna.nullable is False
    assert "clinic" in {fk.column.table.name for fk in columna.foreign_keys}


@pytest.mark.parametrize("nombre", OPERATIVAS)
async def test_base_real_exige_clinic_id_not_null(db_session: AsyncSession, nombre: str) -> None:
    fila = (
        await db_session.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :t AND column_name = 'clinic_id'"
            ),
            {"t": nombre},
        )
    ).scalar_one()
    assert fila == "NO"
