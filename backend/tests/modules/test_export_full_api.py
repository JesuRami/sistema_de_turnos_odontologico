"""Exportación completa: ZIP por lotes, solo la clínica propia y auditada (C-13, S2)."""

from __future__ import annotations

import csv
import io
import json
import zipfile

import httpx
import pytest
from app.core.settings import Settings
from app.models import AuthEvent, AuthEventType
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.appointment_helpers import PACIENTE_NOMBRE, make_agenda
from tests.conftest import MutableClock
from tests.report_helpers import alta
from tests.waitlist_helpers import make_entry, make_offer

pytestmark = pytest.mark.integration


async def _zip(client: httpx.AsyncClient, agenda: object, formato: str) -> zipfile.ZipFile:
    respuesta = await client.get(
        "/api/exports/full",
        params={"format": formato},
        headers=agenda.headers["admin"],  # type: ignore[attr-defined]
    )
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.headers["content-type"] == "application/zip"
    assert "attachment" in respuesta.headers["content-disposition"]
    return zipfile.ZipFile(io.BytesIO(respuesta.content))


async def test_csv_trae_los_tres_archivos_de_la_clinica(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    otra = await make_agenda(db_session, redis_client, settings)
    await alta(app_client, agenda, 10)
    await alta(app_client, otra, 10)

    paquete = await _zip(app_client, agenda, "csv")

    assert sorted(paquete.namelist()) == [
        "appointment_events.csv",
        "appointments.csv",
        "patients.csv",
        "waiting_list_entries.csv",
        "waitlist_events.csv",
        "waitlist_offers.csv",
    ]
    turnos = list(csv.DictReader(io.StringIO(paquete.read("appointments.csv").decode("utf-8-sig"))))
    pacientes = list(csv.DictReader(io.StringIO(paquete.read("patients.csv").decode("utf-8-sig"))))
    eventos = list(
        csv.DictReader(io.StringIO(paquete.read("appointment_events.csv").decode("utf-8-sig")))
    )
    assert len(turnos) == len(eventos) == 1
    assert {p["id"] for p in pacientes} == {str(agenda.patient.id)}
    assert pacientes[0]["full_name"] == PACIENTE_NOMBRE
    assert turnos[0]["patient_id"] == str(agenda.patient.id)


async def test_json_trae_los_mismos_tres_conjuntos(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    await alta(app_client, agenda, 10)

    paquete = await _zip(app_client, agenda, "json")

    assert sorted(paquete.namelist()) == [
        "appointment_events.json",
        "appointments.json",
        "patients.json",
        "waiting_list_entries.json",
        "waitlist_events.json",
        "waitlist_offers.json",
    ]
    # Sin lista de espera: los tres conjuntos de C-12 vienen vacíos.
    for nombre in ("waiting_list_entries", "waitlist_offers", "waitlist_events"):
        assert json.loads(paquete.read(f"{nombre}.json")) == []
    turnos = json.loads(paquete.read("appointments.json"))
    assert len(turnos) == 1
    assert turnos[0]["status"] == "confirmed"
    assert json.loads(paquete.read("appointment_events.json"))[0]["event"] == "created"


async def test_exporta_archivados_y_fusionados_y_neutraliza_formulas(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    await db_session.execute(
        text(
            "UPDATE patient SET full_name = '=HIPERVINCULO(1)', archived_at = now() WHERE id = :i"
        ),
        {"i": agenda.patient.id},
    )

    paquete = await _zip(app_client, agenda, "csv")

    fila = next(csv.DictReader(io.StringIO(paquete.read("patients.csv").decode("utf-8-sig"))))
    assert fila["full_name"] == "'=HIPERVINCULO(1)"
    assert fila["archived_at"] != ""
    assert "merged_into_patient_id" in fila


async def test_formato_invalido_y_roles_no_admin(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)

    invalido = await app_client.get(
        "/api/exports/full", params={"format": "xml"}, headers=agenda.headers["admin"]
    )
    recepcion = await app_client.get("/api/exports/full", headers=agenda.headers["recepcion"])

    assert (invalido.status_code, invalido.json()) == (422, {"detail": "invalid_format"})
    assert recepcion.status_code == 403


async def test_cada_exportacion_queda_auditada_sin_datos_de_pacientes(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)
    await alta(app_client, agenda, 10)

    await _zip(app_client, agenda, "csv")

    evento = (
        await db_session.execute(
            select(AuthEvent).where(
                AuthEvent.clinic_id == agenda.staff.clinic.id,
                AuthEvent.event == AuthEventType.DATA_EXPORTED,
            )
        )
    ).scalar_one()
    assert evento.user_id == agenda.staff.admin.id
    assert evento.payload == {
        "format": "csv",
        "counts": {
            "appointments": 1,
            "patients": 1,
            "appointment_events": 1,
            "waiting_list_entries": 0,
            "waitlist_offers": 0,
            "waitlist_events": 0,
        },
    }
    assert PACIENTE_NOMBRE not in json.dumps(evento.payload)


async def test_exporta_la_lista_de_espera_de_la_clinica(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    """C-12: entradas, ofertas y eventos de la lista de espera, solo de la clínica propia."""
    from datetime import timedelta

    from app.models import ActorType, WaitlistEvent, WaitlistEventType

    agenda = await make_agenda(db_session, redis_client, settings)
    otra = await make_agenda(db_session, redis_client, settings)
    entradas = []
    for a in (agenda, otra):
        entry = await make_entry(db_session, a.staff.clinic, a.patient, notes="Nota ficticia")
        oferta = await make_offer(
            db_session,
            entry,
            professional=a.staff.professional,
            chair=a.staff.chair,
            starts_at=agenda_clock.current + timedelta(days=3),
            now=agenda_clock.current,
        )
        db_session.add(
            WaitlistEvent(
                clinic_id=a.staff.clinic.id,
                entry_id=entry.id,
                offer_id=oferta.id,
                event=WaitlistEventType.OFFER_CREATED,
                actor_type=ActorType.SYSTEM,
                payload={"mode": "auto"},
            )
        )
        entradas.append((entry, oferta))
    await db_session.flush()

    paquete = await _zip(app_client, agenda, "csv")

    def _leer(nombre: str) -> list[dict[str, str]]:
        return list(csv.DictReader(io.StringIO(paquete.read(nombre).decode("utf-8-sig"))))

    [fila_entrada] = _leer("waiting_list_entries.csv")
    [fila_oferta] = _leer("waitlist_offers.csv")
    [fila_evento] = _leer("waitlist_events.csv")
    assert fila_entrada["id"] == str(entradas[0][0].id)
    assert fila_entrada["notes"] == "Nota ficticia"
    assert fila_oferta["id"] == str(entradas[0][1].id)
    assert fila_oferta["status"] == "pending"
    assert fila_evento["event"] == "offer_created"


async def test_lista_de_espera_vacia_solo_con_encabezados(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    agenda_clock: MutableClock,
) -> None:
    agenda = await make_agenda(db_session, redis_client, settings)

    paquete = await _zip(app_client, agenda, "csv")

    for nombre in ("waiting_list_entries", "waitlist_offers", "waitlist_events"):
        lineas = paquete.read(f"{nombre}.csv").decode("utf-8-sig").strip().splitlines()
        assert len(lineas) == 1
        assert lineas[0].startswith("id,")
