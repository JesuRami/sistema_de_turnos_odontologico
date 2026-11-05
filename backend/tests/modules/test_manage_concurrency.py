"""Carreras de la reprogramación por token (C-08, regla 1): un ganador, nada intermedio."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any

import httpx
import pytest
from app.core.settings import Settings
from app.models import Appointment, UserRole
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.appointment_helpers import at
from tests.auth_helpers import issue_session
from tests.booking_helpers import PublicBooking, client_for, committed_app, make_booking
from tests.factories import make_patient, make_user, unique_email
from tests.manage_helpers import Managed, make_managed

pytestmark = pytest.mark.integration

RONDAS = 8  # una por semana: el horizonte de reserva es de 60 días


async def _patch(
    app: FastAPI, url: str, ip: str, cuerpo: dict[str, Any], **kw: Any
) -> httpx.Response:
    async with client_for(app, ip=ip) as client:
        return await client.patch(url, json=cuerpo, **kw)


async def _post(
    app: FastAPI, url: str, cuerpo: dict[str, Any], headers: dict[str, str]
) -> httpx.Response:
    async with client_for(app, ip="10.9.0.1") as client:
        return await client.post(url, json=cuerpo, headers=headers)


def _mover(destino: datetime) -> dict[str, str]:
    return {"action": "reschedule", "starts_at": destino.isoformat()}


async def _inicio(engine: AsyncEngine, appointment_id: uuid.UUID) -> datetime:
    async with AsyncSession(engine) as session:
        inicio = await session.scalar(
            select(Appointment.starts_at).where(Appointment.id == appointment_id)
        )
    assert inicio is not None
    return inicio


async def _staff(
    engine: AsyncEngine, b: PublicBooking, redis: Redis, settings: Settings
) -> tuple[dict[str, str], uuid.UUID]:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        recepcion = await make_user(
            session,
            b.clinic,
            email=unique_email("recepcion.ficticia"),
            role=UserRole.RECEPCION,
            must_change_password=False,
        )
        paciente = await make_patient(session, b.clinic, full_name="Paciente Recepcion Ficticio")
        await session.commit()
    return (await issue_session(redis, settings, recepcion)).headers, paciente.id


async def test_dos_reprogramaciones_al_mismo_hueco(
    committed_engine: AsyncEngine, redis_client: Redis, settings: Settings
) -> None:
    async with AsyncSession(committed_engine, expire_on_commit=False) as session:
        b = await make_booking(session)
        pares: list[tuple[Managed, Managed]] = []
        for ronda in range(RONDAS):
            semana = 7 * (ronda + 1)
            uno = await make_managed(session, at(9, days=semana), booking=b)
            dos = await make_managed(session, at(9, 30, days=semana), booking=b)
            pares.append((uno, dos))
        await session.commit()
    app = committed_app(committed_engine, redis_client, settings)

    for ronda, (uno, dos) in enumerate(pares):
        destino = at(11, days=7 * (ronda + 1))
        r1, r2 = await asyncio.gather(
            _patch(app, uno.url, f"10.3.{ronda}.1", _mover(destino)),
            _patch(app, dos.url, f"10.3.{ronda}.2", _mover(destino)),
        )

        assert sorted((r1.status_code, r2.status_code)) == [200, 409], f"{r1.text} {r2.text}"
        perdedor, original = (uno, at(9, days=7 * (ronda + 1)))
        if r1.status_code == 200:
            perdedor, original = (dos, at(9, 30, days=7 * (ronda + 1)))
        respuesta = r2 if r1.status_code == 200 else r1
        assert respuesta.json()["detail"] == "slot_taken"
        assert await _inicio(committed_engine, perdedor.appointment.id) == original
        async with AsyncSession(committed_engine) as session:
            en_destino = await session.scalar(
                select(func.count())
                .select_from(Appointment)
                .where(
                    Appointment.professional_id == b.professional.id,
                    Appointment.starts_at == destino,
                )
            )
        assert en_destino == 1


async def test_recepcion_crea_un_turno_mientras_el_paciente_reprograma(
    committed_engine: AsyncEngine, redis_client: Redis, settings: Settings
) -> None:
    async with AsyncSession(committed_engine, expire_on_commit=False) as session:
        b = await make_booking(session)
        managed = [
            await make_managed(session, at(9, days=7 * (r + 1)), booking=b) for r in range(RONDAS)
        ]
        await session.commit()
    headers, paciente_id = await _staff(committed_engine, b, redis_client, settings)
    app = committed_app(committed_engine, redis_client, settings)

    for ronda, turno in enumerate(managed):
        destino = at(11, days=7 * (ronda + 1))
        alta = {
            "patient_id": str(paciente_id),
            "professional_id": str(b.professional.id),
            "chair_id": str(b.chair.id),
            "starts_at": destino.isoformat(),
        }
        paciente, recepcion = await asyncio.gather(
            _patch(app, turno.url, f"10.4.{ronda}.1", _mover(destino)),
            _post(app, "/api/appointments", alta, headers),
        )

        codigos = sorted((paciente.status_code, recepcion.status_code))
        assert codigos in ([200, 409], [201, 409]), f"{paciente.text} {recepcion.text}"
        async with AsyncSession(committed_engine) as session:
            en_destino = await session.scalar(
                select(func.count())
                .select_from(Appointment)
                .where(
                    Appointment.professional_id == b.professional.id,
                    Appointment.starts_at == destino,
                )
            )
        assert en_destino == 1
        if paciente.status_code == 409:
            assert paciente.json()["detail"] == "slot_taken"
            assert await _inicio(committed_engine, turno.appointment.id) == at(
                9, days=7 * (ronda + 1)
            )


async def test_paciente_y_recepcion_mueven_el_mismo_turno_sin_deadlock(
    committed_engine: AsyncEngine, redis_client: Redis, settings: Settings
) -> None:
    """Orden de locks único (profesional → sillón → turno): ninguno de los dos termina en 500."""
    async with AsyncSession(committed_engine, expire_on_commit=False) as session:
        b = await make_booking(session)
        managed = [
            await make_managed(session, at(9, days=7 * (r + 1)), booking=b) for r in range(RONDAS)
        ]
        await session.commit()
    headers, _ = await _staff(committed_engine, b, redis_client, settings)
    app = committed_app(committed_engine, redis_client, settings)

    for ronda, turno in enumerate(managed):
        semana = 7 * (ronda + 1)
        paciente, recepcion = await asyncio.gather(
            _patch(app, turno.url, f"10.5.{ronda}.1", _mover(at(11, days=semana))),
            _patch(
                app,
                f"/api/appointments/{turno.appointment.id}",
                f"10.5.{ronda}.2",
                {"starts_at": at(12, days=semana).isoformat()},
                headers=headers,
            ),
        )

        assert paciente.status_code in (200, 409), paciente.text
        assert recepcion.status_code in (200, 409), recepcion.text
        assert await _inicio(committed_engine, turno.appointment.id) in (
            at(11, days=semana),
            at(12, days=semana),
        )


async def test_sin_el_prechequeo_la_base_sigue_impidiendo_el_solapamiento(
    committed_engine: AsyncEngine,
    redis_client: Redis,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defensa en profundidad: con `find_conflicts` anulado, el `EXCLUDE` (23P01) da el 409."""
    import app.modules.appointments.service as servicio

    async def _sin_conflictos(*_: Any, **__: Any) -> list[uuid.UUID]:
        return []

    monkeypatch.setattr(servicio, "find_conflicts", _sin_conflictos)
    async with AsyncSession(committed_engine, expire_on_commit=False) as session:
        b = await make_booking(session)
        pares = [
            (
                await make_managed(session, at(9, days=7 * (r + 1)), booking=b),
                await make_managed(session, at(9, 30, days=7 * (r + 1)), booking=b),
            )
            for r in range(RONDAS)
        ]
        await session.commit()
    app = committed_app(committed_engine, redis_client, settings)

    for ronda, (uno, dos) in enumerate(pares):
        destino = at(11, days=7 * (ronda + 1))
        r1, r2 = await asyncio.gather(
            _patch(app, uno.url, f"10.6.{ronda}.1", _mover(destino)),
            _patch(app, dos.url, f"10.6.{ronda}.2", _mover(destino)),
        )

        assert sorted((r1.status_code, r2.status_code)) == [200, 409], f"{r1.text} {r2.text}"
        perdedora = r1 if r1.status_code == 409 else r2
        assert perdedora.json()["detail"] == "slot_taken"
