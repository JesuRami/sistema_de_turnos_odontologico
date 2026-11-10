"""Alta de entradas de la lista de espera desde recepción (C-12; spec waitlist/entries).

Postgres y Redis reales; reloj de la app fijo en `AGENDA_NOW` (lunes 07/01/2030, 08:00 local).
La carrera de dos altas con commits reales está en `test_waitlist_entries_race.py`. Datos
ficticios (regla 13).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from app.core.settings import Settings
from app.models import WaitingListEntry
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.agenda_helpers import make_staff
from tests.conftest import MutableClock
from tests.factories import make_clinic, make_patient, make_professional
from tests.waitlist_helpers import URL, entry_body

pytestmark = pytest.mark.integration


async def _count(db: AsyncSession, patient_id: object) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(WaitingListEntry)
            .where(WaitingListEntry.patient_id == patient_id)
        )
        or 0
    )


async def test_recepcion_anota_una_entrada_minima(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    paciente = await make_patient(db_session, staff.clinic)

    r = await app_client.post(URL, json=entry_body(paciente), headers=staff.headers["recepcion"])

    assert r.status_code == 201, r.text
    cuerpo = r.json()
    assert cuerpo["status"] == "waiting"
    assert cuerpo["source"] == "reception"
    assert cuerpo["professional_id"] is None
    assert cuerpo["patient"]["id"] == str(paciente.id)
    assert cuerpo["pending_offer"] is None


async def test_franja_y_dias_se_guardan(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    paciente = await make_patient(db_session, staff.clinic)

    r = await app_client.post(
        URL,
        json=entry_body(
            paciente,
            professional_id=str(staff.professional.id),
            time_from="14:00",
            time_to="18:00",
            weekdays=[3, 1],
            notes="Prefiere la tarde",
        ),
        headers=staff.headers["admin"],
    )

    assert r.status_code == 201, r.text
    cuerpo = r.json()
    assert cuerpo["time_from"] == "14:00:00"
    assert cuerpo["weekdays"] == [1, 3]
    assert cuerpo["notes"] == "Prefiere la tarde"


@pytest.mark.parametrize(
    ("cambios", "detalle"),
    [
        ({"date_from": "2030-01-20", "date_to": "2030-01-10"}, "invalid_range"),
        ({"date_from": "2030-01-06"}, "invalid_range"),
        ({"date_to": "2030-03-09"}, "range_too_large"),
        ({"time_from": "18:00", "time_to": "14:00"}, "invalid_time_window"),
        ({"time_from": "14:00"}, "invalid_time_window"),
        ({"weekdays": [7]}, "invalid_weekdays"),
        ({"weekdays": []}, "invalid_weekdays"),
        ({"weekdays": [1, 1]}, "invalid_weekdays"),
        ({"notes": "Llamar al +54 11 5555-0101"}, "invalid_note"),
        ({"notes": "x" * 201}, "invalid_note"),
    ],
)
async def test_validaciones_del_alta(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
    cambios: dict[str, Any],
    detalle: str,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    paciente = await make_patient(db_session, staff.clinic)

    r = await app_client.post(
        URL, json=entry_body(paciente, **cambios), headers=staff.headers["recepcion"]
    )

    assert r.status_code == 422, r.text
    assert r.json()["detail"] == detalle
    assert await _count(db_session, paciente.id) == 0


async def test_ultimo_dia_del_horizonte_se_admite(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    paciente = await make_patient(db_session, staff.clinic)

    r = await app_client.post(
        URL, json=entry_body(paciente, date_to="2030-03-08"), headers=staff.headers["recepcion"]
    )

    assert r.status_code == 201, r.text


async def test_campo_desconocido_se_rechaza(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    paciente = await make_patient(db_session, staff.clinic)

    r = await app_client.post(
        URL, json=entry_body(paciente, status="converted"), headers=staff.headers["recepcion"]
    )

    assert r.status_code == 422


async def test_duplicado_responde_con_la_existente(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    paciente = await make_patient(db_session, staff.clinic)
    cuerpo = entry_body(paciente, professional_id=str(staff.professional.id))
    primera = await app_client.post(URL, json=cuerpo, headers=staff.headers["recepcion"])

    r = await app_client.post(URL, json=cuerpo, headers=staff.headers["recepcion"])

    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "already_waiting"
    assert r.json()["entry_id"] == primera.json()["id"]
    assert await _count(db_session, paciente.id) == 1


async def test_profesional_distinto_es_otra_cola(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    paciente = await make_patient(db_session, staff.clinic)
    await app_client.post(URL, json=entry_body(paciente), headers=staff.headers["recepcion"])

    r = await app_client.post(
        URL,
        json=entry_body(paciente, professional_id=str(staff.professional.id)),
        headers=staff.headers["recepcion"],
    )

    assert r.status_code == 201, r.text


async def test_paciente_de_otra_clinica(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    ajeno = await make_patient(db_session, await make_clinic(db_session))

    r = await app_client.post(URL, json=entry_body(ajeno), headers=staff.headers["recepcion"])

    assert r.status_code == 422
    assert r.json()["detail"] == "invalid_patient"


async def test_paciente_archivado(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    paciente = await make_patient(db_session, staff.clinic, archived_at=agenda_clock.current)

    r = await app_client.post(URL, json=entry_body(paciente), headers=staff.headers["recepcion"])

    assert r.status_code == 422
    assert r.json()["detail"] == "invalid_patient"


async def test_profesional_de_otra_clinica(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    paciente = await make_patient(db_session, staff.clinic)
    ajeno = await make_professional(db_session, await make_clinic(db_session))

    r = await app_client.post(
        URL,
        json=entry_body(paciente, professional_id=str(ajeno.id)),
        headers=staff.headers["recepcion"],
    )

    assert r.status_code == 422
    assert r.json()["detail"] == "invalid_resource"


async def test_profesional_inactivo(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    paciente = await make_patient(db_session, staff.clinic)
    inactivo = await make_professional(db_session, staff.clinic, active=False)

    r = await app_client.post(
        URL,
        json=entry_body(paciente, professional_id=str(inactivo.id)),
        headers=staff.headers["recepcion"],
    )

    assert r.status_code == 409
    assert r.json()["detail"] == "resource_inactive"


async def test_odontologo_no_anota(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    paciente = await make_patient(db_session, staff.clinic)

    r = await app_client.post(URL, json=entry_body(paciente), headers=staff.headers["odontologo"])

    assert r.status_code == 403
    assert r.json()["detail"] == "forbidden_role"


async def test_sin_sesion(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    paciente = await make_patient(db_session, staff.clinic)

    r = await app_client.post(URL, json=entry_body(paciente))

    assert r.status_code == 401


async def test_alta_escribe_evento(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    paciente = await make_patient(db_session, staff.clinic)
    r = await app_client.post(URL, json=entry_body(paciente), headers=staff.headers["recepcion"])

    eventos = await app_client.get(
        f"{URL}/{r.json()['id']}/events", headers=staff.headers["recepcion"]
    )

    assert eventos.status_code == 200, eventos.text
    [evento] = eventos.json()["items"]
    assert evento["event"] == "entry_created"
    assert evento["actor_type"] == "user"
    assert "full_name" not in str(evento["payload"])
