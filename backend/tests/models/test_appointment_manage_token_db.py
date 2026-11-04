"""Invariantes de base de `appointment.manage_token_hash` (C-07, D8/D10).

Se insertan filas directo (sin servicio): la base defiende sola que todo turno online
tenga un hash de gestión de 32 bytes (SHA-256) y que el hash sea único.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

import pytest
from app.models import AppointmentOrigin, AppointmentStatus
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import (
    make_appointment,
    make_chair,
    make_clinic,
    make_patient,
    make_professional,
)

pytestmark = pytest.mark.integration

T10 = datetime(2030, 1, 7, 13, 0, tzinfo=UTC)  # lunes 10:00 en Buenos Aires


def _hash(seed: str) -> bytes:
    return hashlib.sha256(seed.encode()).digest()


async def _turno(db_session: AsyncSession, **overrides: Any) -> None:
    clinic = await make_clinic(db_session)
    await make_appointment(
        db_session,
        clinic,
        patient=await make_patient(db_session, clinic),
        professional=await make_professional(db_session, clinic),
        chair=await make_chair(db_session, clinic),
        starts_at=T10,
        **overrides,
    )


_ONLINE: dict[str, Any] = {
    "origin": AppointmentOrigin.ONLINE,
    "status": AppointmentStatus.PENDING,
}


async def test_turno_online_sin_hash_viola_el_check(db_session: AsyncSession) -> None:
    with pytest.raises(IntegrityError, match="ck_appointment_online_has_manage_token"):
        async with db_session.begin_nested():
            await _turno(db_session, manage_token_hash=None, **_ONLINE)


@pytest.mark.parametrize("largo", [0, 31, 33])
async def test_hash_de_largo_distinto_de_32_viola_el_check(
    db_session: AsyncSession, largo: int
) -> None:
    with pytest.raises(IntegrityError, match="ck_appointment_manage_token_hash_length"):
        async with db_session.begin_nested():
            await _turno(db_session, manage_token_hash=b"\x01" * largo, **_ONLINE)


async def test_turno_online_con_hash_de_32_bytes_es_valido(db_session: AsyncSession) -> None:
    await _turno(db_session, manage_token_hash=_hash("a"), **_ONLINE)


async def test_turno_de_recepcion_sin_hash_es_valido(db_session: AsyncSession) -> None:
    await _turno(db_session, manage_token_hash=None)


async def test_dos_turnos_con_el_mismo_hash_violan_la_unicidad(db_session: AsyncSession) -> None:
    await _turno(db_session, manage_token_hash=_hash("repetido"), **_ONLINE)
    with pytest.raises(IntegrityError, match="uq_appointment_manage_token_hash"):
        async with db_session.begin_nested():
            await _turno(db_session, manage_token_hash=_hash("repetido"), **_ONLINE)


async def test_varios_turnos_sin_hash_no_chocan_por_unicidad(db_session: AsyncSession) -> None:
    await _turno(db_session, manage_token_hash=None)
    await _turno(db_session, manage_token_hash=None)
