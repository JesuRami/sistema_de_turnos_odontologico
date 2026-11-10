"""Rol `app_writer` contra Postgres real (C-14, D7; diferido de C-05). Regla 9: sin mocks.

El usuario de login se crea con `app.ops.db_roles.provision` (el mismo camino que el servicio
`migrate`), así se prueban juntos el verificador SCRAM, la membresía y los privilegios.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator

import asyncpg
import pytest
from alembic import command
from app.ops.db_privileges import APP_ROLE, APPEND_ONLY_TABLES
from app.ops.db_roles import ProvisioningError, provision, scram_sha256_verifier, validate
from sqlalchemy.engine import make_url

from tests.db_utils import alembic_config, run_admin

pytestmark = pytest.mark.integration

CLAVE = "clave-de-prueba-app-writer-0001"


@pytest.fixture()
def app_user(temp_database: str) -> Iterator[tuple[str, str]]:
    """Base temporal migrada + usuario de login miembro de `app_writer` (se borra al final)."""
    command.upgrade(alembic_config(), "head")
    usuario = f"turnos_app_t{uuid.uuid4().hex[:10]}"
    creado = asyncio.run(provision(temp_database, usuario, CLAVE))
    assert creado is True
    url = make_url(temp_database).set(username=usuario, password=CLAVE)
    try:
        yield usuario, url.render_as_string(hide_password=False).replace("+asyncpg", "", 1)
    finally:
        run_admin(f"DROP ROLE IF EXISTS {usuario}")


async def _como_app(dsn: str, sql: str) -> object:
    conn = await asyncpg.connect(dsn)
    try:
        return await conn.fetchval(sql)
    finally:
        await conn.close()


async def _como_dueno(dsn: str, sql: str) -> object:
    conn = await asyncpg.connect(dsn.replace("+asyncpg", "", 1))
    try:
        return await conn.fetchval(sql)
    finally:
        await conn.close()


def _denegado(dsn: str, sql: str) -> bool:
    try:
        asyncio.run(_como_app(dsn, sql))
    except asyncpg.InsufficientPrivilegeError:
        return True
    return False


def test_la_app_lee_e_inserta_pero_no_borra_turnos_ni_pacientes(app_user: tuple[str, str]) -> None:
    _, dsn = app_user
    assert asyncio.run(_como_app(dsn, "SELECT count(*) FROM appointment")) == 0
    for tabla in ("appointment", "patient", "clinic", "waiting_list_entry", "reminder_job"):
        assert _denegado(dsn, f"DELETE FROM {tabla}"), tabla
        assert _denegado(dsn, f"TRUNCATE {tabla}"), tabla


@pytest.mark.parametrize("tabla", APPEND_ONLY_TABLES)
def test_append_only_sin_update_ni_delete(app_user: tuple[str, str], tabla: str) -> None:
    _, dsn = app_user
    assert asyncio.run(_como_app(dsn, f"SELECT count(*) FROM {tabla}")) == 0
    assert _denegado(dsn, f"UPDATE {tabla} SET id = id")
    assert _denegado(dsn, f"DELETE FROM {tabla}")


def test_la_app_puede_insertar_eventos_y_actualizar_tablas_operativas(
    app_user: tuple[str, str], temp_database: str
) -> None:
    _, dsn = app_user
    clinica = asyncio.run(
        _como_app(
            dsn,
            "INSERT INTO clinic (name, slug) VALUES ('Clínica Ficticia Rol', "
            f"'clinica-rol-{uuid.uuid4().hex[:8]}') RETURNING id",
        )
    )
    asyncio.run(_como_app(dsn, f"UPDATE clinic SET name = 'Otra Ficticia' WHERE id = '{clinica}'"))
    usuario = asyncio.run(
        _como_app(
            dsn,
            'INSERT INTO "user" (clinic_id, email, password_hash, role) '
            f"VALUES ('{clinica}', 'rol.ficticio@example.com', '$argon2id$relleno', 'admin') "
            "RETURNING id",
        )
    )
    asyncio.run(
        _como_app(
            dsn,
            "INSERT INTO agenda_config_event "
            "(clinic_id, actor_user_id, entity, entity_id, action, changes) "
            f"VALUES ('{clinica}', '{usuario}', 'clinic_policy', '{clinica}', 'updated', "
            "'{}'::jsonb) RETURNING id",
        )
    )
    total = asyncio.run(_como_dueno(temp_database, "SELECT count(*) FROM agenda_config_event"))
    assert total == 1


def test_la_app_no_toca_alembic_version_ni_crea_tablas(app_user: tuple[str, str]) -> None:
    _, dsn = app_user
    assert asyncio.run(_como_app(dsn, "SELECT count(*) FROM alembic_version")) == 1
    assert _denegado(dsn, "UPDATE alembic_version SET version_num = 'x'")
    assert _denegado(dsn, "CREATE TABLE tabla_intrusa (id int)")


def test_provision_es_idempotente_y_actualiza_la_clave(
    app_user: tuple[str, str], temp_database: str
) -> None:
    usuario, dsn = app_user
    nueva = "otra-clave-de-prueba-app-0002"
    assert asyncio.run(provision(temp_database, usuario, nueva)) is False
    with pytest.raises(asyncpg.InvalidPasswordError):
        asyncio.run(_como_app(dsn, "SELECT 1"))
    ok = make_url(dsn).set(password=nueva).render_as_string(hide_password=False)
    assert asyncio.run(_como_app(ok, "SELECT 1")) == 1


def test_el_usuario_no_tiene_privilegios_de_administracion(
    app_user: tuple[str, str], temp_database: str
) -> None:
    usuario, _ = app_user
    fila = asyncio.run(
        _como_dueno(
            temp_database,
            "SELECT rolsuper OR rolcreatedb OR rolcreaterole FROM pg_roles "
            f"WHERE rolname = '{usuario}'",
        )
    )
    assert fila is False
    miembro = asyncio.run(
        _como_dueno(temp_database, f"SELECT pg_has_role('{usuario}', '{APP_ROLE}', 'member')")
    )
    assert miembro is True


@pytest.mark.parametrize(
    ("usuario", "clave"),
    [
        ("Turnos", CLAVE),
        ("app_writer", CLAVE),
        ("turnos_app", "corta"),
        ("turnos_app", "clave con espacios no vale"),
    ],
)
def test_validacion_de_usuario_y_clave(usuario: str, clave: str) -> None:
    with pytest.raises(ProvisioningError):
        validate(usuario, clave)
        scram_sha256_verifier(clave)


def test_verificador_scram_es_estable_con_la_misma_sal() -> None:
    sal = b"\x00" * 16
    a = scram_sha256_verifier(CLAVE, salt=sal)
    assert a == scram_sha256_verifier(CLAVE, salt=sal)
    assert a.startswith("SCRAM-SHA-256$4096:")
    assert CLAVE not in a
