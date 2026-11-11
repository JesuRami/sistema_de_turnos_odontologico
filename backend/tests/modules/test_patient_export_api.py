"""Exportación por paciente (C-14, D10): acceso/portabilidad mínimos, auditada. Postgres + Redis.

Incluye la regresión del bug hallado en C-14: la exportación JSON fallaba con una entrada de lista
de espera con franja horaria (`datetime.time` no era serializable).
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime, time

import httpx
import pytest
from app.core.settings import Settings
from app.models import (
    AuthEvent,
    AuthEventType,
    Consent,
    ConsentSource,
    ConsentStatus,
    ReminderChannel,
)
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.agenda_helpers import make_staff
from tests.factories import make_appointment, make_clinic, make_patient
from tests.waitlist_helpers import make_entry

pytestmark = pytest.mark.integration

NOMBRE = "Paciente Export Ficticio"
INICIO = datetime(2030, 1, 15, 13, 0, tzinfo=UTC)


def _url(patient_id: object) -> str:
    return f"/api/exports/patients/{patient_id}"


async def test_admin_exporta_los_datos_del_paciente_y_queda_auditado(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    paciente = await make_patient(db_session, staff.clinic, full_name=NOMBRE)
    otro = await make_patient(db_session, staff.clinic, full_name="Otro Paciente Ficticio")
    turno = await make_appointment(
        db_session,
        staff.clinic,
        patient=paciente,
        professional=staff.professional,
        chair=staff.chair,
        starts_at=INICIO,
    )
    await make_appointment(
        db_session,
        staff.clinic,
        patient=otro,
        professional=staff.professional,
        chair=staff.chair,
        starts_at=INICIO.replace(hour=15),
    )
    await make_entry(db_session, staff.clinic, paciente, time_from=time(9, 0), time_to=time(12, 30))
    db_session.add(
        Consent(
            clinic_id=staff.clinic.id,
            patient_id=paciente.id,
            channel=ReminderChannel.WHATSAPP,
            status=ConsentStatus.OPT_IN,
            source=ConsentSource.RECEPTION,
            changed_by_user_id=staff.admin.id,
        )
    )
    await db_session.flush()

    respuesta = await app_client.get(_url(paciente.id), headers=staff.headers["admin"])

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.headers["cache-control"] == "no-store"
    assert respuesta.headers["content-disposition"].startswith("attachment;")
    doc = respuesta.json()
    assert doc["format"] == "patient-export/v1"
    assert doc["patient"]["full_name"] == NOMBRE
    assert [t["id"] for t in doc["appointments"]] == [str(turno.id)]
    assert doc["waiting_list_entries"][0]["time_from"] == "09:00:00"
    assert len(doc["consents"]) == 1
    # Solo los datos de ESTE paciente.
    assert "Otro Paciente Ficticio" not in respuesta.text

    auditoria = (
        await db_session.execute(
            select(AuthEvent.payload).where(
                AuthEvent.clinic_id == staff.clinic.id,
                AuthEvent.event == AuthEventType.DATA_EXPORTED,
            )
        )
    ).scalar_one()
    assert auditoria["scope"] == "patient"
    assert auditoria["patient_id"] == str(paciente.id)
    assert auditoria["counts"]["appointments"] == 1
    # Regla 13: el evento no lleva datos personales.
    assert NOMBRE not in json.dumps(auditoria)
    assert paciente.phone_e164 is not None
    assert paciente.phone_e164 not in json.dumps(auditoria)


async def test_paciente_de_otra_clinica_es_404_y_solo_admin(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    ajena = await make_clinic(db_session)
    de_otra = await make_patient(db_session, ajena, full_name=NOMBRE)
    propio = await make_patient(db_session, staff.clinic, full_name=NOMBRE)

    otra_clinica = await app_client.get(_url(de_otra.id), headers=staff.headers["admin"])
    recepcion = await app_client.get(_url(propio.id), headers=staff.headers["recepcion"])
    odontologo = await app_client.get(_url(propio.id), headers=staff.headers["odontologo"])
    con_parametro = await app_client.get(
        _url(propio.id), params={"clinic_id": str(ajena.id)}, headers=staff.headers["admin"]
    )

    assert (otra_clinica.status_code, otra_clinica.json()) == (404, {"detail": "not_found"})
    assert (recepcion.status_code, odontologo.status_code) == (403, 403)
    assert con_parametro.status_code == 422


async def test_regresion_exportacion_completa_json_con_franja_horaria(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    paciente = await make_patient(db_session, staff.clinic, full_name=NOMBRE)
    await make_entry(db_session, staff.clinic, paciente, time_from=time(8, 0), time_to=time(10, 0))

    respuesta = await app_client.get(
        "/api/exports/full", params={"format": "json"}, headers=staff.headers["admin"]
    )

    assert respuesta.status_code == 200
    with zipfile.ZipFile(io.BytesIO(respuesta.content)) as zf:
        entradas = json.loads(zf.read("waiting_list_entries.json"))
    assert entradas[0]["time_from"] == "08:00:00"
