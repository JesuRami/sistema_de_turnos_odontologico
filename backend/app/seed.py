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
- El teléfono de contacto sintético (C-08) también se carga solo al crear la clínica:
  reejecutar no pisa el que el admin haya cambiado desde las políticas.
- Las plantillas de notificación por defecto (C-09: alta + 72/24/3 h, WhatsApp y email) se
  siembran en cada corrida con `ON CONFLICT DO NOTHING`: se repone la que falte y nunca se pisa
  el texto ni el estado que el admin haya editado.
- `SEED_BOOKING_DEMO=true` (opcional, C-07): la clínica nueva queda con reserva pública
  habilitada, el profesional de ejemplo activo y reservable, y una regla lunes-viernes
  09:00-13:00 de 30 min sobre el sillón (clínica demo / E2E). Sin el flag, la clínica no
  queda pública: habilitar `booking_enabled` es una decisión explícita (solo seed).
"""

import asyncio
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.database import async_database_url
from app.core.security import hash_password
from app.models import Chair, Clinic, Professional, ScheduleRule, User, UserRole
from app.modules.reminders.seeding import seed_default_templates

SEED_VARS = ("SEED_CLINIC_SLUG", "SEED_CLINIC_NAME", "SEED_ADMIN_EMAIL", "SEED_ADMIN_PASSWORD")
SAMPLE_CHAIR_NAME = "Sillón 1"
SAMPLE_PROFESSIONAL_NAME = "Profesional Ficticio de Ejemplo"
# Teléfono de contacto de la clínica (C-08): rango ficticio AMBA 5555, nunca uno real (regla 13).
SAMPLE_CONTACT_PHONE = "+541155550100"
DEMO_WEEKDAYS = range(5)  # lunes a viernes
DEMO_SLOT_MIN = 30
_TRUTHY = frozenset({"1", "true", "yes", "si"})


class SeedConfigError(Exception):
    """Falta una variable obligatoria del seed (el mensaje nombra la variable, nunca valores)."""


@dataclass(frozen=True, repr=False)
class SeedConfig:
    """Parámetros del seed; `repr` oculto para no filtrar la contraseña provisoria."""

    clinic_slug: str
    clinic_name: str
    admin_email: str
    admin_password: str
    booking_demo: bool = False
    demo_users: bool = False
    recepcion_email: str = "recepcion@example.com"
    recepcion_password: str | None = None
    odontologo_email: str = "odontologo@example.com"
    odontologo_password: str | None = None

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
        booking_demo=environ.get("SEED_BOOKING_DEMO", "").strip().lower() in _TRUTHY,
        demo_users=environ.get("SEED_DEMO_USERS", "").strip().lower() in _TRUTHY,
        recepcion_email=environ.get("SEED_RECEPCION_EMAIL", "recepcion@example.com").strip()
        or "recepcion@example.com",
        recepcion_password=environ.get("SEED_RECEPCION_PASSWORD", "").strip() or None,
        odontologo_email=environ.get("SEED_ODONTOLOGO_EMAIL", "odontologo@example.com").strip()
        or "odontologo@example.com",
        odontologo_password=environ.get("SEED_ODONTOLOGO_PASSWORD", "").strip() or None,
    )


async def seed_clinic(session: AsyncSession, config: SeedConfig) -> bool:
    """Siembra el tenant dentro de la transacción de `session` (no hace commit).

    Devuelve `True` si la clínica se creó y `False` si ya existía.
    """
    created_id = await session.scalar(
        pg_insert(Clinic)
        .values(
            name=config.clinic_name, slug=config.clinic_slug, contact_phone=SAMPLE_CONTACT_PHONE
        )
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
    # Siempre (idempotente): repone una plantilla faltante sin pisar las que el admin editó.
    await seed_default_templates(session, clinic_id)
    professional: Professional | None = None
    if created_id is not None:
        chair = Chair(clinic_id=clinic_id, name=SAMPLE_CHAIR_NAME, active=True)
        professional = Professional(
            clinic_id=clinic_id, display_name=SAMPLE_PROFESSIONAL_NAME, active=config.booking_demo
        )
        session.add_all([chair, professional])
        await session.flush()
        if config.booking_demo:
            await _enable_booking_demo(session, clinic_id, chair, professional)

    if config.demo_users:
        prof_id = (
            professional.id
            if professional is not None
            else await session.scalar(
                select(Professional.id).where(Professional.clinic_id == clinic_id).limit(1)
            )
        )
        await _seed_demo_staff(session, clinic_id, prof_id, config)

    return created_id is not None


async def _seed_demo_staff(
    session: AsyncSession, clinic_id: object, professional_id: object | None, config: SeedConfig
) -> None:
    """Siembra usuarios de prueba para recepción y odontólogo (solo datos sintéticos)."""
    recepcion_pwd = config.recepcion_password or config.admin_password
    odontologo_pwd = config.odontologo_password or config.admin_password

    await session.execute(
        pg_insert(User)
        .values(
            clinic_id=clinic_id,
            email=config.recepcion_email.strip().lower(),
            password_hash=hash_password(recepcion_pwd),
            role=UserRole.RECEPCION,
            must_change_password=False,
        )
        .on_conflict_do_nothing(index_elements=["clinic_id", "email"])
    )
    if professional_id is not None:
        await session.execute(
            pg_insert(User)
            .values(
                clinic_id=clinic_id,
                email=config.odontologo_email.strip().lower(),
                password_hash=hash_password(odontologo_pwd),
                role=UserRole.ODONTOLOGO,
                professional_id=professional_id,
                must_change_password=False,
            )
            .on_conflict_do_nothing(index_elements=["clinic_id", "email"])
        )


async def _enable_booking_demo(
    session: AsyncSession, clinic_id: object, chair: Chair, professional: Professional
) -> None:
    """Clínica demo reservable: reserva habilitada y plantilla lunes-viernes (datos ficticios)."""
    await session.execute(update(Clinic).where(Clinic.id == clinic_id).values(booking_enabled=True))
    # Un día de holgura: la zona de la clínica puede ir un día atrás de UTC.
    hoy = datetime.now(UTC).date() - timedelta(days=1)
    session.add_all(
        ScheduleRule(
            clinic_id=clinic_id,
            professional_id=professional.id,
            chair_id=chair.id,
            weekday=weekday,
            start_time=time(9),
            end_time=time(13),
            slot_duration_min=DEMO_SLOT_MIN,
            valid_from=hoy,
        )
        for weekday in DEMO_WEEKDAYS
    )
    await session.flush()


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
    if config.demo_users:
        print("  Usuarios demo activos para todos los roles (admin, recepcion, odontologo).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
