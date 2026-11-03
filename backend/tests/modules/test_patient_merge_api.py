"""`POST /api/patients/{id}/merge`: fusión asistida de duplicados (C-06 tareas 3.1/3.2, D9)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
import pytest
from app.core.settings import Settings
from app.models import (
    Appointment,
    AppointmentEvent,
    AppointmentEventType,
    AppointmentStatus,
    CancellationReason,
    Patient,
    PatientMerge,
)
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.agenda_helpers import Staff, make_staff
from tests.factories import make_appointment, make_clinic, make_patient

pytestmark = pytest.mark.integration

NOMBRE = "Irma Ficticia Duplicada"


async def _merge(
    client: httpx.AsyncClient,
    staff: Staff,
    source: uuid.UUID,
    target: uuid.UUID,
    rol: str = "recepcion",
    /,
    **extra: object,
) -> httpx.Response:
    return await client.post(
        f"/api/patients/{source}/merge",
        json={"into_patient_id": str(target), **extra},
        headers=staff.headers[rol],
    )


async def _turno(
    db_session: AsyncSession, staff: Staff, patient: Patient, hora: int, **extra: object
) -> Appointment:
    return await make_appointment(
        db_session,
        staff.clinic,
        patient=patient,
        professional=staff.professional,
        chair=staff.chair,
        starts_at=datetime(2030, 1, 7, hora, tzinfo=UTC),
        **extra,  # type: ignore[arg-type]
    )


async def _releer(db_session: AsyncSession, model: type[Patient], row_id: uuid.UUID) -> Patient:
    db_session.expire_all()
    fila = await db_session.get(model, row_id)
    assert fila is not None
    return fila


@pytest.mark.parametrize("rol", ["admin", "recepcion"])
async def test_fusion_mueve_turnos_archiva_y_audita(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    rol: str,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    conservado = await make_patient(db_session, staff.clinic, full_name=NOMBRE)
    duplicado = await make_patient(
        db_session, staff.clinic, full_name=NOMBRE.upper(), email="irma@example.com"
    )
    ids = (conservado.id, duplicado.id)
    vigente = await _turno(db_session, staff, duplicado, 13)
    cancelado = await _turno(
        db_session,
        staff,
        duplicado,
        14,
        status=AppointmentStatus.CANCELLED,
        cancelled_at=datetime(2030, 1, 1, tzinfo=UTC),
        cancellation_reason=CancellationReason.PACIENTE,
    )
    turnos = sorted([str(vigente.id), str(cancelado.id)])

    response = await _merge(app_client, staff, ids[1], ids[0], rol)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source_patient_id"] == str(ids[1])
    assert body["target_patient_id"] == str(ids[0])
    assert body["moved_appointments"] == 2
    assert sorted(body["appointment_ids"]) == turnos
    assert body["filled_fields"] == ["email"]
    assert NOMBRE not in response.text and "irma@example.com" not in response.text

    db_session.expire_all()
    fuente = await db_session.get(Patient, ids[1])
    destino = await db_session.get(Patient, ids[0])
    assert fuente is not None and destino is not None
    assert fuente.archived_at is not None
    assert fuente.merged_into_patient_id == ids[0]
    assert destino.email == "irma@example.com"
    assert destino.archived_at is None
    movidos = (
        (
            await db_session.execute(
                select(Appointment.patient_id).where(
                    Appointment.id.in_([uuid.UUID(t) for t in turnos])
                )
            )
        )
        .scalars()
        .all()
    )
    assert set(movidos) == {ids[0]}

    eventos = (
        (
            await db_session.execute(
                select(AppointmentEvent).where(
                    AppointmentEvent.appointment_id.in_([uuid.UUID(t) for t in turnos])
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(eventos) == 2
    for evento in eventos:
        assert evento.event == AppointmentEventType.UPDATED
        assert evento.payload["patient_id"] == [str(ids[1]), str(ids[0])]
        assert evento.payload["reason"] == "patient_merge"
        assert evento.payload["merge_id"] == body["merge_id"]

    registro = (
        await db_session.execute(
            select(PatientMerge).where(PatientMerge.id == uuid.UUID(body["merge_id"]))
        )
    ).scalar_one()
    assert registro.source_patient_id == ids[1]
    assert sorted(registro.appointment_ids) == turnos
    assert registro.filled_fields == ["email"]
    assert "irma" not in str(registro.filled_fields)


async def test_conservado_mantiene_su_telefono_y_su_opt_in(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    conservado = await make_patient(db_session, staff.clinic)
    duplicado = await make_patient(
        db_session, staff.clinic, whatsapp_opt_in=True, dni="00000002", email="dup@example.com"
    )
    telefono, ids = conservado.phone_e164, (conservado.id, duplicado.id)

    response = await _merge(app_client, staff, ids[1], ids[0])

    assert response.status_code == 200
    assert sorted(response.json()["filled_fields"]) == ["dni", "email"]
    destino = await _releer(db_session, Patient, ids[0])
    assert isinstance(destino, Patient)
    assert destino.phone_e164 == telefono
    assert destino.whatsapp_opt_in is False


async def test_duplicado_sin_turnos(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    conservado = await make_patient(db_session, staff.clinic)
    duplicado = await make_patient(db_session, staff.clinic)

    response = await _merge(app_client, staff, duplicado.id, conservado.id)

    assert response.status_code == 200
    assert response.json()["moved_appointments"] == 0
    assert response.json()["appointment_ids"] == []


async def test_fusionado_deja_de_aparecer_y_no_acepta_turnos(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    conservado = await make_patient(db_session, staff.clinic, full_name="Jacinta Ficticia")
    duplicado = await make_patient(db_session, staff.clinic, full_name="Jacinta Ficticia")
    ids = (conservado.id, duplicado.id)
    await _merge(app_client, staff, ids[1], ids[0])

    busqueda = await app_client.get(
        "/api/patients", params={"q": "jacinta ficticia"}, headers=staff.headers["recepcion"]
    )
    detalle = await app_client.get(f"/api/patients/{ids[1]}", headers=staff.headers["admin"])

    assert [p["id"] for p in busqueda.json()["items"]] == [str(ids[0])]
    assert detalle.status_code == 200
    assert detalle.json()["merged_into_patient_id"] == str(ids[0])


# ---------------------------------------------------------------- rechazos


async def test_rechazos_son_422_invalid_merge_y_no_cambian_nada(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    conservado = await make_patient(db_session, staff.clinic)
    duplicado = await make_patient(db_session, staff.clinic)
    archivado = await make_patient(
        db_session, staff.clinic, archived_at=datetime(2029, 1, 1, tzinfo=UTC)
    )
    ajeno = await make_patient(db_session, await make_clinic(db_session))
    ids = {
        "conservado": conservado.id,
        "duplicado": duplicado.id,
        "archivado": archivado.id,
        "ajeno": ajeno.id,
    }

    casos = [
        (ids["duplicado"], ids["duplicado"]),
        (ids["archivado"], ids["conservado"]),
        (ids["duplicado"], ids["archivado"]),
        (ids["duplicado"], ids["ajeno"]),
        (ids["ajeno"], ids["conservado"]),
        (ids["duplicado"], uuid.uuid4()),
        (uuid.uuid4(), ids["conservado"]),
    ]
    respuestas = [await _merge(app_client, staff, s, t) for s, t in casos]

    for response in respuestas:
        assert response.status_code == 422, response.text
        assert response.json() == {"detail": "invalid_merge"}
    fila = await _releer(db_session, Patient, ids["duplicado"])
    assert isinstance(fila, Patient) and fila.archived_at is None
    total = (await db_session.execute(select(PatientMerge))).scalars().all()
    assert [r for r in total if r.clinic_id == staff.clinic.id] == []


async def test_ya_fusionado_no_se_fusiona_otra_vez(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    a = await make_patient(db_session, staff.clinic)
    b = await make_patient(db_session, staff.clinic)
    c = await make_patient(db_session, staff.clinic)
    ids = (a.id, b.id, c.id)
    assert (await _merge(app_client, staff, ids[1], ids[0])).status_code == 200

    otra_vez = await _merge(app_client, staff, ids[1], ids[2])

    assert otra_vez.status_code == 422
    assert otra_vez.json()["detail"] == "invalid_merge"


@pytest.mark.parametrize("extra", [{"clinic_id": str(uuid.uuid4())}, {"force": True}])
async def test_body_con_campos_extra_es_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    extra: dict[str, object],
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    a = await make_patient(db_session, staff.clinic)
    b = await make_patient(db_session, staff.clinic)
    response = await _merge(app_client, staff, b.id, a.id, **extra)
    assert response.status_code == 422


async def test_odontologo_no_fusiona(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    a = await make_patient(db_session, staff.clinic)
    b = await make_patient(db_session, staff.clinic)
    response = await _merge(app_client, staff, b.id, a.id, "odontologo")
    assert response.status_code == 403
    assert response.json()["detail"] == "forbidden_role"
