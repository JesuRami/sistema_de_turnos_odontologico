"""Timeouts por conexión y traducción de errores reales de Postgres (C-14, D3/D4). Regla 9.

Prueba la parte frágil del contrato: que el SQLSTATE de asyncpg llegue a través de SQLAlchemy y
que `map_db_error` lo traduzca. Una carrera sobre la misma fila (lo que hacen los `FOR UPDATE` de
C-05/C-12) no cuelga: espera `DB_LOCK_TIMEOUT_MS` y sale como `409 concurrent_update`.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from app.common.exceptions import map_db_error, sqlstate_of
from app.core.database import create_engine
from app.core.settings import Settings
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.integration


def _settings(**cambios: Any) -> Settings:
    return Settings().model_copy(update=cambios)  # type: ignore[call-arg]


async def test_lock_ocupado_sale_como_409_concurrent_update(temp_database: str) -> None:
    settings = _settings(DB_LOCK_TIMEOUT_MS=200, DB_STATEMENT_TIMEOUT_MS=5_000)
    engine = create_engine(temp_database, settings)
    try:
        async with engine.begin() as setup:
            await setup.execute(text("CREATE TABLE turno_ficticio (id int PRIMARY KEY)"))
            await setup.execute(text("INSERT INTO turno_ficticio VALUES (1)"))
        async with engine.connect() as duenio, engine.connect() as segundo:
            await duenio.begin()
            await duenio.execute(text("SELECT id FROM turno_ficticio WHERE id = 1 FOR UPDATE"))
            await segundo.begin()
            inicio = asyncio.get_running_loop().time()
            with pytest.raises(DBAPIError) as exc_info:
                await segundo.execute(text("SELECT id FROM turno_ficticio WHERE id = 1 FOR UPDATE"))
            espera = asyncio.get_running_loop().time() - inicio
            await segundo.rollback()
            await duenio.rollback()
    finally:
        await engine.dispose()

    assert sqlstate_of(exc_info.value) == "55P03"
    assert map_db_error(exc_info.value) == (409, "concurrent_update", {"Retry-After": "1"})
    assert espera < 2.0  # no esperó indefinidamente


async def test_statement_timeout_sale_como_503_db_timeout(temp_database: str) -> None:
    engine = create_engine(temp_database, _settings(DB_STATEMENT_TIMEOUT_MS=100))
    try:
        async with engine.connect() as conn:
            with pytest.raises(DBAPIError) as exc_info:
                await conn.execute(text("SELECT pg_sleep(2)"))
    finally:
        await engine.dispose()

    assert sqlstate_of(exc_info.value) == "57014"
    assert map_db_error(exc_info.value) == (503, "db_timeout", {"Retry-After": "5"})


async def test_violacion_de_unicidad_no_manejada_sale_como_409_conflict(temp_database: str) -> None:
    engine = create_engine(temp_database, _settings())
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE unico_ficticio (tel text UNIQUE)"))
            await conn.execute(text("INSERT INTO unico_ficticio VALUES ('+5491155550111')"))
        async with engine.connect() as conn:
            with pytest.raises(DBAPIError) as exc_info:
                await conn.execute(text("INSERT INTO unico_ficticio VALUES ('+5491155550111')"))
    finally:
        await engine.dispose()

    assert map_db_error(exc_info.value) == (409, "conflict", {})


async def test_cada_conexion_lleva_sus_parametros_de_sesion(temp_database: str) -> None:
    settings = _settings(DB_STATEMENT_TIMEOUT_MS=1234, DB_LOCK_TIMEOUT_MS=567)
    engine = create_engine(temp_database, settings, application_name="turnos-worker")
    try:
        async with engine.connect() as conn:
            fila = (
                await conn.execute(
                    text(
                        "SELECT current_setting('statement_timeout'), "
                        "current_setting('lock_timeout'), current_setting('application_name')"
                    )
                )
            ).one()
    finally:
        await engine.dispose()

    assert tuple(fila) == ("1234ms", "567ms", "turnos-worker")
