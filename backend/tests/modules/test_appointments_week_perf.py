"""Consulta de una semana con 500 turnos (C-06 tarea 3.4, US-010 CA-3 del lado de la API).

La meta de punta a punta (< 2 s visible en la SPA) se mide en Playwright; acá se
acota la API: la semana entera sale en una página, en menos de 500 ms, y con
20 000 turnos de ruido de otra clínica el plan usa un índice (no seq scan).
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from app.core.settings import Settings
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.agenda_helpers import make_staff
from tests.factories import make_chair, make_clinic, make_patient, make_professional, make_user

pytestmark = pytest.mark.integration

LUNES = datetime(2030, 1, 7, 3, 0, tzinfo=UTC)  # lunes 00:00 en Buenos Aires
HASTA = LUNES + timedelta(days=7)
PARES = 10  # profesional + sillón
DIAS = 7
TURNOS_POR_DIA = 8  # 10 × 7 × 8 = 560 ≥ 500

_INSERT_SEMANA = text("""
    INSERT INTO appointment (clinic_id, patient_id, professional_id, chair_id, starts_at,
                             ends_at, occupied_until, status, origin, created_by_user_id)
    SELECT :clinic_id, :patient_id, r.professional_id, r.chair_id,
           s.inicio, s.inicio + interval '30 minutes', s.inicio + interval '30 minutes',
           'confirmed', 'reception', :user_id
    FROM jsonb_to_recordset(CAST(:recursos AS jsonb))
         AS r(professional_id uuid, chair_id uuid),
         LATERAL (
           SELECT CAST(:lunes AS timestamptz) + make_interval(days => d, hours => 12)
                  + make_interval(mins => 30 * k) AS inicio
           FROM generate_series(0, :dias - 1) d, generate_series(0, :por_dia - 1) k
         ) s
    LIMIT 500
    """)

_INSERT_RUIDO = text("""
    INSERT INTO appointment (clinic_id, patient_id, professional_id, chair_id, starts_at,
                             ends_at, occupied_until, status, origin, created_by_user_id,
                             cancelled_at, cancellation_reason)
    SELECT :clinic_id, :patient_id, :professional_id, :chair_id,
           CAST(:lunes AS timestamptz) + make_interval(hours => n),
           CAST(:lunes AS timestamptz) + make_interval(hours => n, mins => 30),
           CAST(:lunes AS timestamptz) + make_interval(hours => n, mins => 30),
           'cancelled', 'reception', :user_id, now(), 'otro'
    FROM generate_series(-10000, 9999) n
    """)


async def test_semana_de_500_turnos_en_una_pagina_y_rapida(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    patient = await make_patient(db_session, staff.clinic)
    recursos = [
        {
            "professional_id": str(
                (await make_professional(db_session, staff.clinic, display_name=f"Dr. P{n}")).id
            ),
            "chair_id": str((await make_chair(db_session, staff.clinic, name=f"S{n}")).id),
        }
        for n in range(PARES)
    ]
    await db_session.execute(
        _INSERT_SEMANA,
        {
            "clinic_id": staff.clinic.id,
            "patient_id": patient.id,
            "user_id": staff.admin.id,
            "recursos": json.dumps(recursos),
            "lunes": LUNES,
            "dias": DIAS,
            "por_dia": TURNOS_POR_DIA,
        },
    )
    otra = await make_clinic(db_session)
    await db_session.execute(
        _INSERT_RUIDO,
        {
            "clinic_id": otra.id,
            "patient_id": (await make_patient(db_session, otra)).id,
            "professional_id": (await make_professional(db_session, otra)).id,
            "chair_id": (await make_chair(db_session, otra)).id,
            "user_id": (await make_user(db_session, otra)).id,
            "lunes": LUNES,
        },
    )
    await db_session.execute(text("ANALYZE appointment"))
    params: dict[str, str | int] = {
        "from": LUNES.isoformat(),
        "to": HASTA.isoformat(),
        "limit": 500,
    }

    await app_client.get("/api/appointments", params=params, headers=staff.headers["recepcion"])
    inicio = time.perf_counter()
    response = await app_client.get(
        "/api/appointments", params=params, headers=staff.headers["recepcion"]
    )
    duracion = time.perf_counter() - inicio

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["items"]) == 500
    assert body["next_cursor"] is None
    assert duracion < 0.5, f"semana en {duracion:.3f} s"

    plan = "\n".join(
        str(r[0])
        for r in await db_session.execute(
            text(
                "EXPLAIN SELECT id FROM appointment WHERE clinic_id = :c "
                "AND starts_at < :hasta AND occupied_until > :desde"
            ),
            {"c": staff.clinic.id, "desde": LUNES, "hasta": HASTA},
        )
    )
    assert "Seq Scan on appointment" not in plan, plan
