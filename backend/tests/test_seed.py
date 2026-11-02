"""Seed idempotente por clínica: mínimo operable, solo datos sintéticos, sin secretos en salida."""

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest
from alembic import command
from app.core.security import verify_password
from app.models import Chair, Clinic, Patient, Professional, User, UserRole
from app.seed import SeedConfig, SeedConfigError, read_seed_config, seed_clinic
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db_utils import alembic_config

CLAVE = "clave-seed-de-prueba-no-real-7"
ENV_COMPLETO = {
    "SEED_CLINIC_SLUG": "clinica-seed-ficticia",
    "SEED_CLINIC_NAME": "Clínica Seed Ficticia",
    "SEED_ADMIN_EMAIL": "admin@example.com",
    "SEED_ADMIN_PASSWORD": CLAVE,
}
BACKEND_DIR = Path(__file__).resolve().parents[1]


def _config(slug: str = "clinica-seed-ficticia") -> SeedConfig:
    return SeedConfig(
        clinic_slug=slug,
        clinic_name="Clínica Seed Ficticia",
        admin_email="admin@example.com",
        admin_password=CLAVE,
    )


async def _contar(session: AsyncSession, modelo: type, **filtros: object) -> int:
    stmt = select(func.count()).select_from(modelo)
    for campo, valor in filtros.items():
        stmt = stmt.where(getattr(modelo, campo) == valor)
    return int(await session.scalar(stmt) or 0)


async def test_seed_sobre_db_vacia_crea_el_minimo_operable(db_session: AsyncSession) -> None:
    await seed_clinic(db_session, _config())

    clinic = (
        await db_session.execute(select(Clinic).where(Clinic.slug == "clinica-seed-ficticia"))
    ).scalar_one()
    assert clinic.reminder_steps == [
        {"offset_h": 72, "channel": "whatsapp"},
        {"offset_h": 24, "channel": "whatsapp"},
        {"offset_h": 3, "channel": "whatsapp"},
    ]
    admin = (await db_session.execute(select(User).where(User.clinic_id == clinic.id))).scalar_one()
    assert admin.role is UserRole.ADMIN
    assert admin.must_change_password is True
    assert admin.email == "admin@example.com"
    assert verify_password(CLAVE, admin.password_hash) is True
    chair = (
        await db_session.execute(select(Chair).where(Chair.clinic_id == clinic.id))
    ).scalar_one()
    assert (chair.name, chair.active) == ("Sillón 1", True)
    prof = (
        await db_session.execute(select(Professional).where(Professional.clinic_id == clinic.id))
    ).scalar_one()
    assert prof.active is False
    assert "Ficticio" in prof.display_name or "Ejemplo" in prof.display_name
    assert await _contar(db_session, Patient, clinic_id=clinic.id) == 0


async def test_doble_ejecucion_no_duplica_ni_cambia_el_hash(db_session: AsyncSession) -> None:
    await seed_clinic(db_session, _config())
    hash_1 = (await db_session.execute(select(User.password_hash))).scalar_one()

    await seed_clinic(db_session, _config())

    assert await _contar(db_session, Clinic, slug="clinica-seed-ficticia") == 1
    assert await _contar(db_session, User) == 1
    assert await _contar(db_session, Chair) == 1
    assert await _contar(db_session, Professional) == 1
    assert (await db_session.execute(select(User.password_hash))).scalar_one() == hash_1


async def test_segunda_ejecucion_con_otra_clave_no_pisa_la_del_admin(
    db_session: AsyncSession,
) -> None:
    await seed_clinic(db_session, _config())
    otra = SeedConfig("clinica-seed-ficticia", "Otro Nombre", "admin@example.com", "otra-clave-9")

    await seed_clinic(db_session, otra)

    admin = (await db_session.execute(select(User))).scalar_one()
    assert verify_password(CLAVE, admin.password_hash) is True
    assert verify_password("otra-clave-9", admin.password_hash) is False


async def test_slugs_distintos_son_tenants_independientes(db_session: AsyncSession) -> None:
    await seed_clinic(db_session, _config("clinica-seed-uno"))
    await seed_clinic(db_session, _config("clinica-seed-dos"))

    assert await _contar(db_session, Clinic) == 2
    assert await _contar(db_session, User) == 2
    assert await _contar(db_session, Chair) == 2


def test_lectura_de_config_completa() -> None:
    config = read_seed_config(ENV_COMPLETO)
    assert config == _config()


@pytest.mark.parametrize("faltante", sorted(ENV_COMPLETO))
def test_variable_faltante_aborta_nombrandola_sin_filtrar_la_clave(faltante: str) -> None:
    env = {k: v for k, v in ENV_COMPLETO.items() if k != faltante}
    with pytest.raises(SeedConfigError) as exc:
        read_seed_config(env)
    assert faltante in str(exc.value)
    assert CLAVE not in str(exc.value)


def test_variable_vacia_cuenta_como_faltante() -> None:
    with pytest.raises(SeedConfigError, match="SEED_ADMIN_PASSWORD"):
        read_seed_config({**ENV_COMPLETO, "SEED_ADMIN_PASSWORD": "  "})


async def test_seed_no_loguea_clave_ni_hash(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        await seed_clinic(db_session, _config())
    hash_admin = (await db_session.execute(select(User.password_hash))).scalar_one()
    assert CLAVE not in caplog.text
    assert hash_admin not in caplog.text


def _correr_seed(env_extra: dict[str, str], database_url: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DATABASE_URL": database_url, **env_extra}
    return subprocess.run(
        [sys.executable, "-m", "app.seed"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _contar_sync(database_url: str, tabla: str) -> int:
    import asyncio

    import asyncpg

    async def _q() -> int:
        url = make_url(database_url)
        conn = await asyncpg.connect(
            user=url.username,
            password=url.password,
            host=url.host,
            port=url.port,
            database=url.database,
        )
        try:
            return int(await conn.fetchval(f'SELECT count(*) FROM "{tabla}"'))
        finally:
            await conn.close()

    return asyncio.run(_q())


def test_cli_dos_corridas_idempotentes_y_salida_sin_secretos(temp_database: str) -> None:
    command.upgrade(alembic_config(), "head")

    primera = _correr_seed(ENV_COMPLETO, temp_database)
    segunda = _correr_seed(ENV_COMPLETO, temp_database)

    assert primera.returncode == 0, primera.stderr
    assert segunda.returncode == 0, segunda.stderr
    for corrida in (primera, segunda):
        salida = corrida.stdout + corrida.stderr
        assert CLAVE not in salida
        assert "$argon2" not in salida
    assert _contar_sync(temp_database, "clinic") == 1
    assert _contar_sync(temp_database, "user") == 1
    assert _contar_sync(temp_database, "chair") == 1
    assert _contar_sync(temp_database, "professional") == 1
    assert _contar_sync(temp_database, "patient") == 0


def test_cli_sin_password_aborta_nombrando_la_variable_y_no_persiste(temp_database: str) -> None:
    command.upgrade(alembic_config(), "head")
    env = {k: v for k, v in ENV_COMPLETO.items() if k != "SEED_ADMIN_PASSWORD"}
    entorno = {k: v for k, v in os.environ.items() if k != "SEED_ADMIN_PASSWORD"}
    resultado = subprocess.run(
        [sys.executable, "-m", "app.seed"],
        cwd=BACKEND_DIR,
        env={**entorno, "DATABASE_URL": temp_database, **env},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert resultado.returncode != 0
    assert "SEED_ADMIN_PASSWORD" in resultado.stdout + resultado.stderr
    assert _contar_sync(temp_database, "clinic") == 0
