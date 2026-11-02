"""Seed idempotente de un tenant nuevo (`python -m app.seed`, ejecutar desde `backend/`).

Crea el mínimo operable: 1 clínica con la configuración por defecto, 1 admin con
cambio de contraseña obligatorio, 1 sillón "Sillón 1" activo y 1 profesional de
ejemplo inactivo. Sin pacientes. Solo datos sintéticos (regla dura 13).

Reglas:
- La credencial provisoria SOLO viene del entorno (regla 6); si falta, aborta
  nombrando la variable y sin tocar la base.
- Nunca imprime la contraseña ni el hash.
- Todo corre en una única transacción y es idempotente por slug (`ON CONFLICT
  DO NOTHING`): reejecutar no duplica filas ni pisa la clave de un admin existente.
- El sillón y el profesional de ejemplo se crean solo con la clínica; reejecutar
  sobre una clínica existente no los vuelve a crear aunque se hayan renombrado.
"""

import asyncio
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.database import async_database_url
from app.core.security import hash_password
from app.models import Chair, Clinic, Professional, User, UserRole

SEED_VARS = ("SEED_CLINIC_SLUG", "SEED_CLINIC_NAME", "SEED_ADMIN_EMAIL", "SEED_ADMIN_PASSWORD")
SAMPLE_CHAIR_NAME = "Sillón 1"
SAMPLE_PROFESSIONAL_NAME = "Profesional Ficticio de Ejemplo"


class SeedConfigError(Exception):
    """Falta una variable obligatoria del seed (el mensaje nombra la variable, nunca valores)."""


@dataclass(frozen=True, repr=False)
class SeedConfig:
    """Parámetros del seed; `repr` oculto para no filtrar la contraseña provisoria."""

    clinic_slug: str
    clinic_name: str
    admin_email: str
    admin_password: str

    def __repr__(self) -> str:
        return f"SeedConfig(clinic_slug={self.clinic_slug!r})"


def read_seed_config(environ: Mapping[str, str]) -> SeedConfig:
    """Lee la configuración del entorno; falla nombrando todas las variables faltantes."""
    values = {name: environ.get(name, "").strip() for name in SEED_VARS}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise SeedConfigError(f"Faltan variables de entorno del seed: {', '.join(missing)}")
    return SeedConfig(
        clinic_slug=values["SEED_CLINIC_SLUG"],
        clinic_name=values["SEED_CLINIC_NAME"],
        admin_email=values["SEED_ADMIN_EMAIL"],
        admin_password=values["SEED_ADMIN_PASSWORD"],
    )


async def seed_clinic(session: AsyncSession, config: SeedConfig) -> bool:
    """Siembra el tenant dentro de la transacción de `session` (no hace commit).

    Devuelve `True` si la clínica se creó y `False` si ya existía.
    """
    created_id = await session.scalar(
        pg_insert(Clinic)
        .values(name=config.clinic_name, slug=config.clinic_slug)
        .on_conflict_do_nothing(index_elements=["slug"])
        .returning(Clinic.id)
    )
    clinic_id = created_id or await session.scalar(
        select(Clinic.id).where(Clinic.slug == config.clinic_slug)
    )
    if clinic_id is None:  # pragma: no cover - imposible dentro de una transacción coherente
        raise RuntimeError("No se pudo resolver la clínica del seed")

    await session.execute(
        pg_insert(User)
        .values(
            clinic_id=clinic_id,
            email=config.admin_email.strip().lower(),
            password_hash=hash_password(config.admin_password),
            role=UserRole.ADMIN,
            must_change_password=True,
        )
        .on_conflict_do_nothing(index_elements=["clinic_id", "email"])
    )
    if created_id is not None:
        session.add(Chair(clinic_id=clinic_id, name=SAMPLE_CHAIR_NAME, active=True))
        session.add(
            Professional(clinic_id=clinic_id, display_name=SAMPLE_PROFESSIONAL_NAME, active=False)
        )
        await session.flush()
    return created_id is not None


async def run_seed(database_url: str, config: SeedConfig) -> bool:
    """Abre su propio engine y corre el seed en UNA transacción (commit al final)."""
    engine = create_async_engine(async_database_url(database_url), poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            async with session.begin():
                return await seed_clinic(session, config)
    finally:
        await engine.dispose()


def main() -> int:
    """Punto de entrada CLI; imprime un resumen sin secretos."""
    try:
        config = read_seed_config(os.environ)
        database_url = os.environ.get("DATABASE_URL", "").strip()
        if not database_url:
            raise SeedConfigError("Falta la variable de entorno: DATABASE_URL")
    except SeedConfigError as error:
        print(f"Seed abortado: {error}", file=sys.stderr)
        return 1
    created = asyncio.run(run_seed(database_url, config))
    estado = "creada" if created else "ya existía (sin cambios)"
    print(f"Seed completo: clínica '{config.clinic_slug}' {estado}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
