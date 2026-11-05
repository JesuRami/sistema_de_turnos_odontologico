"""Seed de la clínica demo con teléfono de contacto sintético (C-08, D12): idempotente."""

from app.models import Clinic
from app.seed import SAMPLE_CONTACT_PHONE, SeedConfig, seed_clinic
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

SLUG = "clinica-seed-telefono-ficticia"


def _config() -> SeedConfig:
    return SeedConfig(
        clinic_slug=SLUG,
        clinic_name="Clínica Seed Ficticia",
        admin_email="admin@example.com",
        admin_password="clave-seed-de-prueba-no-real-7",
    )


async def test_el_seed_deja_un_telefono_sintetico_y_no_lo_pisa_al_reejecutar(
    db_session: AsyncSession,
) -> None:
    await seed_clinic(db_session, _config())
    clinic = (await db_session.execute(select(Clinic).where(Clinic.slug == SLUG))).scalar_one()
    assert clinic.contact_phone == SAMPLE_CONTACT_PHONE
    assert SAMPLE_CONTACT_PHONE.startswith("+54115555")  # rango ficticio (regla 13)

    clinic.contact_phone = "+541155550199"  # el admin lo cambió desde las políticas
    await db_session.flush()
    await seed_clinic(db_session, _config())

    await db_session.refresh(clinic)
    assert clinic.contact_phone == "+541155550199"
    total = await db_session.scalar(
        select(func.count()).select_from(Clinic).where(Clinic.slug == SLUG)
    )
    assert total == 1
