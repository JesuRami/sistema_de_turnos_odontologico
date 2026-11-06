"""Seed de usuarios demo para todos los roles (C-03 / personal de prueba)."""

from app.models import Clinic, Professional, User, UserRole
from app.seed import SeedConfig, read_seed_config, seed_clinic
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

CLAVE = "clave-seed-de-prueba-no-real-7"
ENV_BASE = {
    "SEED_CLINIC_SLUG": "clinica-demo-staff",
    "SEED_CLINIC_NAME": "Clínica Demo Staff",
    "SEED_ADMIN_EMAIL": "admin@example.com",
    "SEED_ADMIN_PASSWORD": CLAVE,
}


def _config(slug: str = "clinica-demo-staff", *, demo_users: bool = True) -> SeedConfig:
    return SeedConfig(
        clinic_slug=slug,
        clinic_name="Clínica Demo Staff",
        admin_email="admin@example.com",
        admin_password=CLAVE,
        demo_users=demo_users,
    )


def test_lectura_de_flag_demo_users_y_correos_por_defecto() -> None:
    env = {**ENV_BASE, "SEED_DEMO_USERS": "true"}
    config = read_seed_config(env)
    assert config.demo_users is True
    assert config.recepcion_email == "recepcion@example.com"
    assert config.odontologo_email == "odontologo@example.com"


def test_lectura_de_correos_personalizados() -> None:
    env = {
        **ENV_BASE,
        "SEED_DEMO_USERS": "1",
        "SEED_RECEPCION_EMAIL": "recep.custom@example.com",
        "SEED_ODONTOLOGO_EMAIL": "odonto.custom@example.com",
    }
    config = read_seed_config(env)
    assert config.demo_users is True
    assert config.recepcion_email == "recep.custom@example.com"
    assert config.odontologo_email == "odonto.custom@example.com"


async def test_seed_con_demo_users_crea_un_usuario_por_cada_rol(db_session: AsyncSession) -> None:
    await seed_clinic(db_session, _config())

    clinic = (
        await db_session.execute(select(Clinic).where(Clinic.slug == "clinica-demo-staff"))
    ).scalar_one()

    prof = (
        await db_session.execute(select(Professional).where(Professional.clinic_id == clinic.id))
    ).scalar_one()

    users = (
        (await db_session.execute(select(User).where(User.clinic_id == clinic.id))).scalars().all()
    )
    assert len(users) == 3

    roles_map = {u.role: u for u in users}
    assert set(roles_map.keys()) == {UserRole.ADMIN, UserRole.RECEPCION, UserRole.ODONTOLOGO}

    admin = roles_map[UserRole.ADMIN]
    assert admin.email == "admin@example.com"
    assert admin.must_change_password is True

    recepcion = roles_map[UserRole.RECEPCION]
    assert recepcion.email == "recepcion@example.com"
    assert recepcion.must_change_password is False

    odontologo = roles_map[UserRole.ODONTOLOGO]
    assert odontologo.email == "odontologo@example.com"
    assert odontologo.professional_id == prof.id
    assert odontologo.must_change_password is False


async def test_reejecucion_con_demo_users_es_idempotente(db_session: AsyncSession) -> None:
    await seed_clinic(db_session, _config())
    await seed_clinic(db_session, _config())

    clinic = (
        await db_session.execute(select(Clinic).where(Clinic.slug == "clinica-demo-staff"))
    ).scalar_one()

    total_users = await db_session.scalar(
        select(func.count()).select_from(User).where(User.clinic_id == clinic.id)
    )
    assert total_users == 3
