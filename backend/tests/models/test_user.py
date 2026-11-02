"""User: rol cerrado, odontólogo↔profesional, email único en minúsculas (Postgres real)."""

import uuid

import pytest
from app.models import User, UserRole
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_clinic, make_professional, make_user


async def test_rol_desconocido_rechazado_por_la_base(db_session: AsyncSession) -> None:
    clinic = await make_clinic(db_session)
    with pytest.raises(DBAPIError, match="user_role"):
        await db_session.execute(
            text(
                'INSERT INTO "user" (clinic_id, email, password_hash, role) '
                "VALUES (:c, 'root@example.com', 'x', 'superadmin')"
            ),
            {"c": clinic.id},
        )
    await db_session.rollback()
    assert await db_session.scalar(select(func.count()).select_from(User)) == 0


@pytest.mark.parametrize("rol", [UserRole.ADMIN, UserRole.RECEPCION])
async def test_admin_y_recepcion_persisten_sin_profesional(
    db_session: AsyncSession, rol: UserRole
) -> None:
    clinic = await make_clinic(db_session)
    user = await make_user(db_session, clinic, role=rol)
    await db_session.refresh(user)
    assert user.role is rol
    assert user.professional_id is None


async def test_odontologo_sin_profesional_viola_check(db_session: AsyncSession) -> None:
    clinic = await make_clinic(db_session)
    with pytest.raises(IntegrityError, match="ck_user_odontologo_requires_professional"):
        await make_user(db_session, clinic, role=UserRole.ODONTOLOGO)


async def test_odontologo_con_profesional_propio_persiste(db_session: AsyncSession) -> None:
    clinic = await make_clinic(db_session)
    professional = await make_professional(db_session, clinic)
    user = await make_user(
        db_session, clinic, role=UserRole.ODONTOLOGO, professional_id=professional.id
    )
    assert user.professional_id == professional.id


async def test_odontologo_con_profesional_de_otra_clinica_viola_fk_compuesta(
    db_session: AsyncSession,
) -> None:
    clinic_a = await make_clinic(db_session)
    clinic_b = await make_clinic(db_session)
    professional_b = await make_professional(db_session, clinic_b)
    with pytest.raises(IntegrityError, match="fk_user_clinic_id_professional_id_professional"):
        await make_user(
            db_session, clinic_a, role=UserRole.ODONTOLOGO, professional_id=professional_b.id
        )


async def test_admin_con_profesional_de_otra_clinica_tambien_viola_fk(
    db_session: AsyncSession,
) -> None:
    clinic_a = await make_clinic(db_session)
    clinic_b = await make_clinic(db_session)
    professional_b = await make_professional(db_session, clinic_b)
    with pytest.raises(IntegrityError, match="fk_user_clinic_id_professional_id_professional"):
        await make_user(db_session, clinic_a, professional_id=professional_b.id)


async def test_email_duplicado_en_la_misma_clinica_viola_unicidad(
    db_session: AsyncSession,
) -> None:
    clinic = await make_clinic(db_session)
    await make_user(db_session, clinic, email="admin@example.com")
    with pytest.raises(IntegrityError, match="uq_user_clinic_id_email"):
        await make_user(db_session, clinic, email="admin@example.com")


async def test_mismo_email_en_otra_clinica_persiste(db_session: AsyncSession) -> None:
    clinic_a = await make_clinic(db_session)
    clinic_b = await make_clinic(db_session)
    await make_user(db_session, clinic_a, email="admin@example.com")
    await make_user(db_session, clinic_b, email="admin@example.com")


async def test_email_con_mayusculas_viola_check(db_session: AsyncSession) -> None:
    clinic = await make_clinic(db_session)
    with pytest.raises(IntegrityError, match="ck_user_email_lowercase"):
        await make_user(db_session, clinic, email="Admin@Example.com")


async def test_defaults_usuario_activo_y_con_cambio_de_clave_obligatorio(
    db_session: AsyncSession,
) -> None:
    clinic = await make_clinic(db_session)
    user = await make_user(db_session, clinic)
    await db_session.refresh(user)
    assert user.active is True
    assert user.must_change_password is True
    assert user.last_login_at is None


async def test_usuario_sin_clinic_id_rechazado(db_session: AsyncSession) -> None:
    db_session.add(
        User(
            clinic_id=None,
            email="x@example.com",
            password_hash="x",
            role=UserRole.ADMIN,
        )
    )
    with pytest.raises(IntegrityError, match="clinic_id"):
        await db_session.flush()


async def test_usuario_de_clinica_inexistente_viola_fk(db_session: AsyncSession) -> None:
    db_session.add(
        User(clinic_id=uuid.uuid4(), email="x@example.com", password_hash="x", role=UserRole.ADMIN)
    )
    with pytest.raises(IntegrityError, match="fk_user_clinic_id_clinic"):
        await db_session.flush()
