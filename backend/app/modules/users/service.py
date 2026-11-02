"""Servicio del dominio users: alta de personal y consulta por email, siempre por clínica.

Reglas: `clinic_id` obligatorio en todo filtro (regla 4); la contraseña solo existe
como hash argon2id y NUNCA se loguea (regla 6/13); errores públicos sin PII.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import DomainError
from app.core.security import hash_password
from app.models import User, UserRole

_INVALID_USER = "Datos de usuario inválidos"


class UsersService:
    """Stub de servicio (los routers delegan aquí, nunca lógica inline)."""

    async def ping(self) -> str:
        """Verifica cableado router→servicio."""
        return "ok"


async def create_staff_user(
    session: AsyncSession,
    clinic_id: uuid.UUID,
    email: str,
    password: str,
    role: UserRole,
    professional_id: uuid.UUID | None = None,
    must_change_password: bool = True,
) -> User:
    """Crea un usuario del personal: email en minúsculas, contraseña como hash argon2id.

    Ante cualquier violación de constraint lanza `DomainError(422)` sin datos personales.
    """
    user = User(
        clinic_id=clinic_id,
        email=email.strip().lower(),
        password_hash=hash_password(password),
        role=role,
        professional_id=professional_id,
        must_change_password=must_change_password,
    )
    try:
        async with session.begin_nested():
            session.add(user)
            await session.flush()
    except IntegrityError:
        raise DomainError(422, _INVALID_USER) from None
    return user


async def get_user_by_email(session: AsyncSession, clinic_id: uuid.UUID, email: str) -> User | None:
    """Usuario de la clínica con ese email (insensible a mayúsculas) o `None`."""
    stmt = select(User).where(User.clinic_id == clinic_id, User.email == email.strip().lower())
    return (await session.execute(stmt)).scalar_one_or_none()
