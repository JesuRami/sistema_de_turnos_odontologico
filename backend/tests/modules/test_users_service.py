"""Servicio de usuarios: alta con hash argon2id, email en minúsculas y aislamiento por clínica."""

import logging

import pytest
from app.common.exceptions import DomainError
from app.core.security import verify_password
from app.models import UserRole
from app.modules.users.service import create_staff_user, get_user_by_email
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_clinic, make_professional

CLAVE = "clave-provisoria-de-prueba-9"


async def test_alta_normaliza_email_hashea_y_marca_cambio_obligatorio(
    db_session: AsyncSession,
) -> None:
    clinic = await make_clinic(db_session)

    user = await create_staff_user(
        db_session, clinic.id, "Recepcion.Ficticia@Example.com", CLAVE, UserRole.RECEPCION
    )
    await db_session.refresh(user)

    assert user.email == "recepcion.ficticia@example.com"
    assert user.password_hash.startswith("$argon2id$")
    assert CLAVE not in user.password_hash
    assert verify_password(CLAVE, user.password_hash) is True
    assert user.must_change_password is True
    assert user.active is True
    assert user.role is UserRole.RECEPCION


async def test_alta_permite_no_exigir_cambio_de_clave(db_session: AsyncSession) -> None:
    clinic = await make_clinic(db_session)
    user = await create_staff_user(
        db_session,
        clinic.id,
        "admin@example.com",
        CLAVE,
        UserRole.ADMIN,
        must_change_password=False,
    )
    assert user.must_change_password is False


async def test_alta_de_odontologo_con_su_profesional(db_session: AsyncSession) -> None:
    clinic = await make_clinic(db_session)
    professional = await make_professional(db_session, clinic)
    user = await create_staff_user(
        db_session,
        clinic.id,
        "odonto@example.com",
        CLAVE,
        UserRole.ODONTOLOGO,
        professional_id=professional.id,
    )
    assert user.professional_id == professional.id


async def test_alta_nunca_registra_la_contrasena_en_logs(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    clinic = await make_clinic(db_session)
    with caplog.at_level(logging.DEBUG):
        user = await create_staff_user(
            db_session, clinic.id, "admin@example.com", CLAVE, UserRole.ADMIN
        )
    registros = caplog.text + " ".join(r.getMessage() for r in caplog.records)
    assert CLAVE not in registros
    assert user.password_hash not in registros


@pytest.mark.parametrize("caso", ["odontologo_sin_profesional", "email_duplicado"])
async def test_alta_invalida_da_error_de_dominio_sin_pii(
    db_session: AsyncSession, caso: str
) -> None:
    clinic = await make_clinic(db_session)
    email = "persona.ficticia@example.com"
    await create_staff_user(db_session, clinic.id, email, CLAVE, UserRole.ADMIN)
    rol = UserRole.ODONTOLOGO if caso == "odontologo_sin_profesional" else UserRole.ADMIN
    email_nuevo = "otra.persona@example.com" if caso == "odontologo_sin_profesional" else email

    with pytest.raises(DomainError) as exc:
        await create_staff_user(db_session, clinic.id, email_nuevo, CLAVE, rol)

    expuesto = f"{exc.value!s} {exc.value.detail} {exc.value!r}"
    assert exc.value.status_code == 422
    assert "example.com" not in expuesto
    assert CLAVE not in expuesto


async def test_get_user_by_email_no_cruza_clinicas(db_session: AsyncSession) -> None:
    clinic_a = await make_clinic(db_session)
    clinic_b = await make_clinic(db_session)
    user_a = await create_staff_user(
        db_session, clinic_a.id, "admin@example.com", CLAVE, UserRole.ADMIN
    )
    user_b = await create_staff_user(
        db_session, clinic_b.id, "admin@example.com", CLAVE, UserRole.ADMIN
    )

    en_a = await get_user_by_email(db_session, clinic_a.id, "admin@example.com")
    en_b = await get_user_by_email(db_session, clinic_b.id, "admin@example.com")

    assert en_a is not None and en_a.id == user_a.id
    assert en_b is not None and en_b.id == user_b.id


async def test_get_user_by_email_de_otra_clinica_devuelve_none(db_session: AsyncSession) -> None:
    clinic_a = await make_clinic(db_session)
    clinic_b = await make_clinic(db_session)
    await create_staff_user(db_session, clinic_b.id, "solo.b@example.com", CLAVE, UserRole.ADMIN)

    assert await get_user_by_email(db_session, clinic_a.id, "solo.b@example.com") is None


async def test_get_user_by_email_ignora_mayusculas_de_la_entrada(db_session: AsyncSession) -> None:
    clinic = await make_clinic(db_session)
    user = await create_staff_user(
        db_session, clinic.id, "admin@example.com", CLAVE, UserRole.ADMIN
    )

    encontrado = await get_user_by_email(db_session, clinic.id, "ADMIN@Example.COM")

    assert encontrado is not None and encontrado.id == user.id
