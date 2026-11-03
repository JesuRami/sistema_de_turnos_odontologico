"""La búsqueda de recepción por nombre usa el índice GIN trigram."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_clinic, make_patient


async def _explain(session: AsyncSession, sql: str, clinic_id: object) -> str:
    rows = await session.execute(text("EXPLAIN " + sql), {"clinic_id": clinic_id})
    return "\n".join(row[0] for row in rows)


async def _clinica_con_muchos_pacientes(session: AsyncSession) -> object:
    clinic = await make_clinic(session)
    await session.execute(
        text(
            "INSERT INTO patient (clinic_id, full_name, email) "
            "SELECT :c, 'Persona Falsa ' || n, 'falsa.' || n || '@example.com' "
            "FROM generate_series(1, 3000) AS n"
        ),
        {"c": clinic.id},
    )
    await make_patient(session, clinic, full_name="Zoila Inventada Ficticia")
    await session.execute(text("ANALYZE patient"))
    await session.execute(text("SET LOCAL enable_seqscan = off"))
    return clinic.id


async def test_ilike_por_nombre_usa_indice_trigram(db_session: AsyncSession) -> None:
    clinic_id = await _clinica_con_muchos_pacientes(db_session)

    plan = await _explain(
        db_session, "SELECT id FROM patient WHERE full_name ILIKE '%inventa%'", clinic_id
    )

    assert "ix_patient_full_name_trgm" in plan, plan


async def test_ilike_por_nombre_con_clinic_id_usa_trigram_si_el_btree_no_compite(
    db_session: AsyncSession,
) -> None:
    """`clinic_id` es predicado adicional (decisión 5.d): con una sola clínica el btree
    por `clinic_id` no es selectivo, así que se lo retira (DDL transaccional, se revierte)
    para comprobar que el GIN sirve la consulta filtrada por clínica. Lo mismo con el
    UNIQUE `(id, clinic_id)` de C-05 (solo existe para la FK compuesta de `appointment`)."""
    clinic_id = await _clinica_con_muchos_pacientes(db_session)
    await db_session.execute(text("DROP INDEX ix_patient_clinic_id_phone_e164"))
    await db_session.execute(
        text("ALTER TABLE patient DROP CONSTRAINT uq_patient_id_clinic_id CASCADE")
    )

    plan = await _explain(
        db_session,
        "SELECT id FROM patient WHERE clinic_id = :clinic_id AND full_name ILIKE '%inventa%'",
        clinic_id,
    )

    assert "ix_patient_full_name_trgm" in plan, plan


async def test_busqueda_por_nombre_devuelve_coincidencias_parciales(
    db_session: AsyncSession,
) -> None:
    clinic = await make_clinic(db_session)
    esperado = await make_patient(db_session, clinic, full_name="Zoila Inventada Pérez")
    await make_patient(db_session, clinic, full_name="Otro Nombre Falso")

    rows = await db_session.execute(
        text("SELECT id FROM patient WHERE clinic_id = :c AND full_name ILIKE '%inventa%'"),
        {"c": clinic.id},
    )

    assert [r[0] for r in rows] == [esperado.id]
