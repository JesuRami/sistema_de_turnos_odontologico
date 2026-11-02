"""Fábricas de datos SINTÉTICOS para tests (regla dura 13).

Todo valor es obviamente falso: nombres inventados, emails @example.com y
teléfonos de rango ficticio. Nunca datos reales.
"""

import itertools
from datetime import date, time
from typing import Any

from app.models import Chair, Clinic, Patient, Professional, ScheduleRule, User, UserRole
from sqlalchemy.ext.asyncio import AsyncSession

_counter = itertools.count(1)


def next_n() -> int:
    """Secuencia monótona para generar valores únicos por test run."""
    return next(_counter)


def unique_slug(prefix: str = "clinica-ficticia") -> str:
    """Slug único y obviamente ficticio."""
    return f"{prefix}-{next_n()}"


def unique_email(local: str = "persona.ficticia") -> str:
    """Email único del dominio reservado example.com."""
    return f"{local}.{next_n()}@example.com"


def unique_phone_e164() -> str:
    """Celular ficticio AMBA en E.164 (+54 9 11 5550-xxxx, rango no asignado)."""
    return f"+549115550{next_n() % 10000:04d}"


async def make_clinic(session: AsyncSession, **overrides: Any) -> Clinic:
    """Clínica sintética persistida (flush) con slug único."""
    values: dict[str, Any] = {"name": "Clínica Ficticia", "slug": unique_slug()}
    values.update(overrides)
    clinic = Clinic(**values)
    session.add(clinic)
    await session.flush()
    return clinic


async def make_professional(
    session: AsyncSession, clinic: Clinic, **overrides: Any
) -> Professional:
    """Profesional sintético de la clínica dada."""
    values: dict[str, Any] = {"clinic_id": clinic.id, "display_name": "Dr. Ficticio Uno"}
    values.update(overrides)
    professional = Professional(**values)
    session.add(professional)
    await session.flush()
    return professional


async def make_chair(session: AsyncSession, clinic: Clinic, **overrides: Any) -> Chair:
    """Sillón sintético de la clínica dada."""
    values: dict[str, Any] = {"clinic_id": clinic.id, "name": "Sillón Ficticio"}
    values.update(overrides)
    chair = Chair(**values)
    session.add(chair)
    await session.flush()
    return chair


async def make_schedule_rule(
    session: AsyncSession,
    clinic: Clinic,
    professional: Professional,
    chair: Chair,
    **overrides: Any,
) -> ScheduleRule:
    """Regla semanal sintética: lunes 09:00-13:00, slots de 30 min, sin fin de vigencia."""
    values: dict[str, Any] = {
        "clinic_id": clinic.id,
        "professional_id": professional.id,
        "chair_id": chair.id,
        "weekday": 0,
        "start_time": time(9, 0),
        "end_time": time(13, 0),
        "slot_duration_min": 30,
        "valid_from": date(2026, 1, 1),
    }
    values.update(overrides)
    rule = ScheduleRule(**values)
    session.add(rule)
    await session.flush()
    return rule


async def make_patient(session: AsyncSession, clinic: Clinic, **overrides: Any) -> Patient:
    """Paciente sintético con teléfono ficticio único (E.164) y sin DNI."""
    values: dict[str, Any] = {
        "clinic_id": clinic.id,
        "full_name": "Paciente Ficticio Uno",
        "phone_e164": unique_phone_e164(),
    }
    values.update(overrides)
    patient = Patient(**values)
    session.add(patient)
    await session.flush()
    return patient


async def make_user(session: AsyncSession, clinic: Clinic, **overrides: Any) -> User:
    """Usuario sintético (rol admin por defecto) con hash de relleno, no verificable."""
    values: dict[str, Any] = {
        "clinic_id": clinic.id,
        "email": unique_email("staff.ficticio"),
        "password_hash": "$argon2id$hash-de-relleno-no-real",
        "role": UserRole.ADMIN,
    }
    values.update(overrides)
    user = User(**values)
    session.add(user)
    await session.flush()
    return user
