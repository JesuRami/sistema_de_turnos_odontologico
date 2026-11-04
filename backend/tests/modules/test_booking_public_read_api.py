"""Lecturas públicas (C-07, D1/D3): catálogo y disponibilidad anónimos, sin filtrar datos ajenos."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, time, timedelta

import httpx
import pytest
from app.models import AppointmentStatus, CancellationReason
from sqlalchemy.ext.asyncio import AsyncSession

from tests.appointment_helpers import at
from tests.booking_helpers import PublicBooking, make_booking
from tests.conftest import MutableClock
from tests.factories import (
    make_appointment,
    make_block,
    make_chair,
    make_clinic,
    make_patient,
    make_professional,
    make_schedule_rule,
)

pytestmark = pytest.mark.integration

NO_ENCONTRADO = {"detail": "booking_not_found"}
PROF_NO_ENCONTRADO = {"detail": "professional_not_found"}


async def _disponibilidad(
    client: httpx.AsyncClient,
    slug: str,
    professional_id: uuid.UUID | str,
    desde: datetime | None = None,
    hasta: datetime | None = None,
) -> httpx.Response:
    return await client.get(
        f"/api/booking/{slug}/availability",
        params={
            "professional_id": str(professional_id),
            "from": (desde or at(0)).isoformat(),
            "to": (hasta or at(0, days=1)).isoformat(),
        },
    )


def _instantes(response: httpx.Response) -> list[datetime]:
    return [datetime.fromisoformat(s["starts_at"]) for s in response.json()["slots"]]


# ------------------------------------------------------------------ catálogo


async def test_catalogo_lista_solo_profesionales_reservables(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    clinic = await make_clinic(db_session, booking_enabled=True, name="Clínica Demo Ficticia")
    uno = await make_booking(db_session, clinic=clinic)
    dos = await make_booking(db_session, clinic=clinic)
    # No reservables: sin regla, sin booking_enabled, inactivo y con sillón inactivo.
    await make_professional(db_session, clinic, display_name="Sin regla")
    deshabilitado = await make_professional(
        db_session, clinic, display_name="Deshabilitado", booking_enabled=False
    )
    inactivo = await make_professional(db_session, clinic, display_name="Inactivo", active=False)
    sillon_inactivo = await make_chair(db_session, clinic, active=False)
    con_sillon_inactivo = await make_professional(
        db_session, clinic, display_name="Sillón inactivo"
    )
    for profesional in (deshabilitado, inactivo):
        await make_schedule_rule(db_session, clinic, profesional, uno.chair)
    await make_schedule_rule(db_session, clinic, con_sillon_inactivo, sillon_inactivo)

    response = await app_client.get(f"/api/booking/{clinic.slug}")

    assert response.status_code == 200, response.text
    cuerpo = response.json()
    assert set(cuerpo) == {"name", "timezone", "professionals"}
    assert cuerpo["name"] == "Clínica Demo Ficticia"
    assert cuerpo["timezone"] == "America/Argentina/Buenos_Aires"
    assert sorted(cuerpo["professionals"], key=lambda p: p["id"]) == sorted(
        [
            {"id": str(uno.professional.id), "display_name": uno.professional.display_name},
            {"id": str(dos.professional.id), "display_name": dos.professional.display_name},
        ],
        key=lambda p: p["id"],
    )


async def test_catalogo_excluye_la_regla_vencida(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    vencida = await make_booking(db_session, valid_to=at(0).date() - timedelta(days=1))

    response = await app_client.get(f"/api/booking/{vencida.slug}")

    assert response.status_code == 200
    assert response.json()["professionals"] == []


async def test_slug_inexistente_y_reserva_deshabilitada_son_indistinguibles(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    apagada = await make_clinic(db_session, booking_enabled=False)
    await make_booking(db_session, clinic=apagada)

    inexistente = await app_client.get("/api/booking/no-existe-xyz")
    deshabilitada = await app_client.get(f"/api/booking/{apagada.slug}")

    assert inexistente.status_code == deshabilitada.status_code == 404
    assert inexistente.json() == deshabilitada.json() == NO_ENCONTRADO


async def test_slug_inexistente_tambien_en_disponibilidad(
    app_client: httpx.AsyncClient, agenda_clock: MutableClock
) -> None:
    response = await _disponibilidad(app_client, "no-existe-xyz", uuid.uuid4())

    assert response.status_code == 404
    assert response.json() == NO_ENCONTRADO


# ------------------------------------------------------------ disponibilidad


async def test_disponibilidad_descuenta_turnos_bloqueos_y_buffer(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session, buffer_min=10, end_time=time(12))
    paciente = await make_patient(db_session, b.clinic)
    await make_appointment(
        db_session,
        b.clinic,
        patient=paciente,
        professional=b.professional,
        chair=b.chair,
        starts_at=at(10),
        buffer_min=10,
    )
    await make_block(
        db_session,
        b.clinic,
        professional=b.professional,
        starts_at=at(11),
        ends_at=at(12),
    )

    response = await _disponibilidad(app_client, b.slug, b.professional.id)

    assert response.status_code == 200, response.text
    assert _instantes(response) == [at(9)]
    assert response.headers["Cache-Control"] == "no-store"


async def test_cancelar_el_turno_libera_el_hueco(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)
    paciente = await make_patient(db_session, b.clinic)
    turno = await make_appointment(
        db_session,
        b.clinic,
        patient=paciente,
        professional=b.professional,
        chair=b.chair,
        starts_at=at(10),
    )
    antes = await _disponibilidad(app_client, b.slug, b.professional.id)
    turno.status = AppointmentStatus.CANCELLED
    turno.cancelled_at = at(8)
    turno.cancellation_reason = CancellationReason.OTRO
    await db_session.flush()

    despues = await _disponibilidad(app_client, b.slug, b.professional.id)

    assert at(10) not in _instantes(antes)
    assert at(10) in _instantes(despues)


async def test_respuesta_sin_ids_de_turnos_pacientes_sillones_ni_pii(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)
    paciente = await make_patient(
        db_session,
        b.clinic,
        full_name="Zoila Reservada Ficticia",
        email="zoila.reservada@example.com",
    )
    turno = await make_appointment(
        db_session,
        b.clinic,
        patient=paciente,
        professional=b.professional,
        chair=b.chair,
        starts_at=at(10),
    )

    response = await _disponibilidad(app_client, b.slug, b.professional.id)

    crudo = response.text
    for dato in (
        str(turno.id),
        str(paciente.id),
        str(b.chair.id),
        "Zoila",
        "zoila.reservada",
        paciente.phone_e164 or "",
        "pending",
        "confirmed",
        "chair",
        "status",
    ):
        assert dato not in crudo, dato
    slots = json.loads(crudo)["slots"]
    assert slots
    for slot in slots:
        assert set(slot) == {"starts_at", "ends_at", "professional_id"}


async def test_no_ofrece_horarios_pasados(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)
    agenda_clock.current = at(10, 15)

    response = await _disponibilidad(app_client, b.slug, b.professional.id)

    assert _instantes(response) == [at(10, 30), at(11), at(11, 30), at(12), at(12, 30)]


async def test_disponibilidad_de_varios_dias_en_la_zona_de_la_clinica(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session, end_time=time(10))

    response = await _disponibilidad(
        app_client, b.slug, b.professional.id, desde=at(0), hasta=at(0, days=14)
    )

    assert _instantes(response) == [at(9), at(9, 30), at(9, days=7), at(9, 30, days=7)]
    assert response.json()["timezone"] == "America/Argentina/Buenos_Aires"


@pytest.mark.parametrize(
    ("dias_desde", "dias_hasta"),
    [(0, 15), (0, 30), (0, 0), (1, 0), (80, 83), (50, 62)],
    ids=["15 días", "30 días", "to == from", "to < from", "desde > horizonte", "to > horizonte"],
)
async def test_rango_invalido_es_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    agenda_clock: MutableClock,
    dias_desde: int,
    dias_hasta: int,
) -> None:
    b = await make_booking(db_session)

    response = await _disponibilidad(
        app_client,
        b.slug,
        b.professional.id,
        desde=at(0, days=dias_desde),
        hasta=at(0, days=dias_hasta),
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid_range"}


async def test_rango_en_el_limite_del_horizonte_es_valido(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)

    response = await _disponibilidad(
        app_client, b.slug, b.professional.id, desde=at(0, days=46), hasta=at(0, days=60)
    )

    assert response.status_code == 200


async def test_fechas_sin_zona_horaria_son_422(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)

    response = await app_client.get(
        f"/api/booking/{b.slug}/availability",
        params={
            "professional_id": str(b.professional.id),
            "from": "2030-01-07T00:00:00",
            "to": "2030-01-08T00:00:00",
        },
    )

    assert response.status_code == 422


async def _no_reservable(db_session: AsyncSession, caso: str, b: PublicBooking) -> uuid.UUID:
    """Id de un profesional que, bajo el slug de `b`, debe verse como inexistente."""
    if caso == "ajeno":
        return (await make_booking(db_session)).professional.id
    if caso == "inexistente":
        return uuid.uuid4()
    if caso == "sin_regla":
        return (await make_professional(db_session, b.clinic)).id
    profesional = await make_professional(
        db_session,
        b.clinic,
        active=caso != "inactivo",
        booking_enabled=caso != "deshabilitado",
    )
    await make_schedule_rule(db_session, b.clinic, profesional, b.chair)
    return profesional.id


@pytest.mark.parametrize("caso", ["ajeno", "inexistente", "sin_regla", "inactivo", "deshabilitado"])
async def test_profesional_no_reservable_responde_como_inexistente(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    agenda_clock: MutableClock,
    caso: str,
) -> None:
    b = await make_booking(db_session)
    professional_id = await _no_reservable(db_session, caso, b)

    response = await _disponibilidad(app_client, b.slug, professional_id)

    assert response.status_code == 404
    assert response.json() == PROF_NO_ENCONTRADO


async def test_reserva_deshabilitada_corta_la_disponibilidad(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    b = await make_booking(db_session)
    b.clinic.booking_enabled = False
    await db_session.flush()

    response = await _disponibilidad(app_client, b.slug, b.professional.id)

    assert response.status_code == 404
    assert response.json() == NO_ENCONTRADO
