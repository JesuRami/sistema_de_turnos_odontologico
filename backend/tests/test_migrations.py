"""Migración c02_core_models contra Postgres 15 real (DB temporal propia por test)."""

from alembic import command

from tests.db_utils import alembic_config, fetch_rows

TABLAS = {"clinic", "professional", "chair", "schedule_rule", "patient", "user"}
INDICES = {
    "uq_clinic_slug",
    "ix_professional_clinic_id_active",
    "ix_chair_clinic_id_active",
    "ix_patient_clinic_id_phone_e164",
    "ix_patient_full_name_trgm",
    "ix_schedule_rule_professional_id_chair_id_weekday",
}


def _tablas(url: str) -> set[str]:
    rows = fetch_rows(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
        "AND tablename <> 'alembic_version'",
        url,
    )
    return {str(r[0]) for r in rows}


def _indices(url: str) -> set[str]:
    return {str(r[0]) for r in fetch_rows("SELECT indexname FROM pg_indexes", url)}


def _enums(url: str) -> set[str]:
    return {str(r[0]) for r in fetch_rows("SELECT typname FROM pg_type WHERE typtype = 'e'", url)}


def _esquema(url: str) -> list[tuple[object, ...]]:
    return fetch_rows(
        "SELECT table_name, column_name, data_type, is_nullable, column_default "
        "FROM information_schema.columns WHERE table_schema = 'public' "
        "ORDER BY table_name, column_name",
        url,
    ) + fetch_rows(
        "SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) "
        "FROM pg_constraint WHERE connamespace = 'public'::regnamespace ORDER BY 1, 2",
        url,
    )


def test_ciclo_upgrade_downgrade_upgrade(temp_database: str) -> None:
    """WHEN upgrade head, downgrade base y upgrade head THEN los tres pasos terminan sin error."""
    cfg = alembic_config()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


def test_esquema_final_identico_tras_el_ciclo(temp_database: str) -> None:
    cfg = alembic_config()
    command.upgrade(cfg, "head")
    primero = _esquema(temp_database)
    command.downgrade(cfg, "c01_base")
    command.upgrade(cfg, "head")

    assert primero != []
    assert _esquema(temp_database) == primero


def test_upgrade_crea_tablas_e_indices_del_change(temp_database: str) -> None:
    command.upgrade(alembic_config(), "head")

    assert _tablas(temp_database) == TABLAS
    assert INDICES <= _indices(temp_database)
    assert _enums(temp_database) == {"user_role"}


def test_indice_trigram_es_gin_con_gin_trgm_ops(temp_database: str) -> None:
    command.upgrade(alembic_config(), "head")

    definicion = fetch_rows(
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_patient_full_name_trgm'",
        temp_database,
    )[0][0]
    assert "USING gin" in str(definicion)
    assert "gin_trgm_ops" in str(definicion)


def test_downgrade_no_deja_tablas_ni_enums_del_change(temp_database: str) -> None:
    cfg = alembic_config()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "c01_base")

    assert _tablas(temp_database) == set()
    assert _enums(temp_database) == set()
    # pg_trgm puede quedar instalada (decisión de diseño 5.i).


def test_modelos_y_migracion_no_divergen(temp_database: str) -> None:
    """Autogenerate contra la DB migrada no debe proponer cambios (drift modelo↔migración)."""
    import asyncio
    import os

    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from app.core.database import async_database_url
    from app.models import Base
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


def test_cli_alembic_desde_la_raiz_del_repo(temp_database: str) -> None:
    """El CLI real (como en CI) resuelve `app` y migra: upgrade, downgrade -1, upgrade."""
    import os
    import subprocess
    import sys

    from tests.db_utils import ROOT

    env = {**os.environ, "DATABASE_URL": temp_database}
    for args in (["upgrade", "head"], ["downgrade", "-1"], ["upgrade", "head"]):
        resultado = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        assert resultado.returncode == 0, resultado.stderr
    assert _tablas(temp_database) == TABLAS
