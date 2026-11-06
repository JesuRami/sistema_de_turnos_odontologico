"""El personal cambia el consentimiento de un paciente (C-10, D9; spec channel-consent).

Postgres y Redis reales; datos ficticios (regla 13).
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import httpx
import pytest
from app.core.settings import Settings
from app.models import (
    Consent,
    ConsentSource,
    ConsentStatus,
    ReminderStatus,
    UserRole,
)
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.agenda_helpers import Staff, make_staff
from tests.factories import make_appointment, make_patient, unique_email
from tests.reminder_helpers import AHORA, make_job, statuses_of

pytestmark = pytest.mark.integration


def _url(patient_id: uuid.UUID, canal: str = "whatsapp") -> str:
    return f"/api/patients/{patient_id}/consent/{canal}"


async def _consentimientos(session: AsyncSession, patient_id: uuid.UUID) -> list[Consent]:
    return list(
        (
            await session.execute(
                select(Consent).where(Consent.patient_id == patient_id).order_by(Consent.changed_at)
            )
        )
        .scalars()
        .all()
    )


async def _staff(db: AsyncSession, redis: Redis, settings: Settings) -> Staff:
    return await make_staff(db, redis, settings)


async def test_recepcion_registra_una_baja_de_whatsapp(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    staff = await _staff(db_session, redis_client, settings)
    paciente = await make_patient(db_session, staff.clinic, whatsapp_opt_in=True)
    turno = await make_appointment(
        db_session,
        staff.clinic,
        patient=paciente,
        professional=staff.professional,
        chair=staff.chair,
        starts_at=AHORA + timedelta(days=30),
    )
    await make_job(db_session, turno)

    respuesta = await app_client.put(
        _url(paciente.id), json={"status": "opt_out"}, headers=staff.headers["recepcion"]
    )

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json() == {"channel": "whatsapp", "status": "opt_out", "changed": True}
    await db_session.refresh(paciente)
    assert paciente.whatsapp_opt_in is False
    [fila] = await _consentimientos(db_session, paciente.id)
    assert (fila.status, fila.source) == (ConsentStatus.OPT_OUT, ConsentSource.RECEPTION)
    assert fila.changed_by_user_id is not None and fila.changed_by_user_id != staff.admin.id
    assert (await statuses_of(db_session, turno.id))[
        "t_24h/whatsapp"
    ] == ReminderStatus.SKIPPED.value


async def test_admin_registra_un_opt_in(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    staff = await _staff(db_session, redis_client, settings)
    paciente = await make_patient(db_session, staff.clinic)

    respuesta = await app_client.put(
        _url(paciente.id), json={"status": "opt_in"}, headers=staff.headers["admin"]
    )

    assert respuesta.status_code == 200
    await db_session.refresh(paciente)
    assert paciente.whatsapp_opt_in is True
    [fila] = await _consentimientos(db_session, paciente.id)
    assert fila.changed_by_user_id == staff.admin.id


async def test_opt_in_redundante_no_agrega_fila(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    staff = await _staff(db_session, redis_client, settings)
    paciente = await make_patient(db_session, staff.clinic)
    for _ in range(2):
        respuesta = await app_client.put(
            _url(paciente.id), json={"status": "opt_in"}, headers=staff.headers["recepcion"]
        )

    assert respuesta.status_code == 200
    assert respuesta.json() == {"channel": "whatsapp", "status": "opt_in", "changed": False}
    assert len(await _consentimientos(db_session, paciente.id)) == 1


async def test_opt_in_de_whatsapp_sin_telefono(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    staff = await _staff(db_session, redis_client, settings)
    paciente = await make_patient(
        db_session, staff.clinic, phone_e164=None, email=unique_email("paciente.ficticio")
    )

    respuesta = await app_client.put(
        _url(paciente.id), json={"status": "opt_in"}, headers=staff.headers["recepcion"]
    )

    assert (respuesta.status_code, respuesta.json()["detail"]) == (422, "phone_required")
    assert await _consentimientos(db_session, paciente.id) == []


async def test_opt_in_de_email_sin_email(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    staff = await _staff(db_session, redis_client, settings)
    paciente = await make_patient(db_session, staff.clinic)

    respuesta = await app_client.put(
        _url(paciente.id, "email"), json={"status": "opt_in"}, headers=staff.headers["recepcion"]
    )

    assert (respuesta.status_code, respuesta.json()["detail"]) == (422, "email_required")


async def test_baja_de_email(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    staff = await _staff(db_session, redis_client, settings)
    paciente = await make_patient(db_session, staff.clinic, email=unique_email("paciente.ficticio"))

    respuesta = await app_client.put(
        _url(paciente.id, "email"), json={"status": "opt_out"}, headers=staff.headers["recepcion"]
    )

    assert respuesta.json() == {"channel": "email", "status": "opt_out", "changed": True}


async def test_paciente_de_otra_clinica_es_404(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    a = await _staff(db_session, redis_client, settings)
    b = await _staff(db_session, redis_client, settings)
    ajeno = await make_patient(db_session, b.clinic)

    respuesta = await app_client.put(
        _url(ajeno.id), json={"status": "opt_out"}, headers=a.headers["recepcion"]
    )

    assert respuesta.status_code == 404
    assert await _consentimientos(db_session, ajeno.id) == []


async def test_paciente_fusionado_es_404(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    staff = await _staff(db_session, redis_client, settings)
    conservado = await make_patient(db_session, staff.clinic)
    fusionado = await make_patient(
        db_session, staff.clinic, merged_into_patient_id=conservado.id, archived_at=AHORA
    )

    respuesta = await app_client.put(
        _url(fusionado.id), json={"status": "opt_out"}, headers=staff.headers["recepcion"]
    )

    assert respuesta.status_code == 404


async def test_odontologo_es_403(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    staff = await _staff(db_session, redis_client, settings)
    paciente = await make_patient(db_session, staff.clinic)

    respuesta = await app_client.put(
        _url(paciente.id),
        json={"status": "opt_out"},
        headers=staff.headers[UserRole.ODONTOLOGO.value],
    )

    assert (respuesta.status_code, respuesta.json()["detail"]) == (403, "forbidden_role")


async def test_sin_sesion_es_401(app_client: httpx.AsyncClient) -> None:
    respuesta = await app_client.put(_url(uuid.uuid4()), json={"status": "opt_out"})

    assert respuesta.status_code == 401


@pytest.mark.parametrize(
    ("canal", "cuerpo"),
    [
        ("whatsapp", {"status": "opt_out", "extra": 1}),
        ("whatsapp", {"status": "talvez"}),
        ("whatsapp", {}),
        ("sms", {"status": "opt_out"}),
    ],
)
async def test_cuerpo_o_canal_invalido_es_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    canal: str,
    cuerpo: dict[str, object],
) -> None:
    staff = await _staff(db_session, redis_client, settings)
    paciente = await make_patient(db_session, staff.clinic)

    respuesta = await app_client.put(
        _url(paciente.id, canal), json=cuerpo, headers=staff.headers["recepcion"]
    )

    assert respuesta.status_code == 422
