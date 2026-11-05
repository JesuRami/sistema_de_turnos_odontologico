"""Resolución del link de gestión y vista (C-08, D2-D5): hash, vigencia, datos mínimos."""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
from app.models import AppointmentStatus
from sqlalchemy.ext.asyncio import AsyncSession

from tests.appointment_helpers import at
from tests.conftest import AGENDA_NOW, MutableClock
from tests.manage_helpers import make_managed, new_token

pytestmark = pytest.mark.integration

NO_ENCONTRADO = {"detail": "manage_link_not_found"}


def _assert_privado(response: httpx.Response) -> None:
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"


# ---------------------------------------------------------------- resolución


async def test_token_valido_resuelve_su_turno(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    managed = await make_managed(db_session, at(10, days=5))

    response = await app_client.get(managed.url)

    assert response.status_code == 200, response.text
    assert response.json()["appointment"]["status"] == "pending"
    _assert_privado(response)


async def test_token_desconocido_y_malformado_son_indistinguibles(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    await make_managed(db_session, at(10, days=5))

    desconocido = await app_client.get(f"/api/manage/{new_token()}")
    malformado = await app_client.get("/api/manage/abcdefghij")

    assert desconocido.status_code == malformado.status_code == 404
    assert desconocido.json() == malformado.json() == NO_ENCONTRADO
    _assert_privado(desconocido)
    _assert_privado(malformado)


async def test_el_token_no_alcanza_otro_turno(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    uno = await make_managed(db_session, at(10, days=5))
    otro = await make_managed(db_session, at(11, days=5), booking=uno.booking)

    response = await app_client.get(uno.url)

    assert response.status_code == 200
    inicio = response.json()["appointment"]["starts_at"]
    assert inicio.startswith(uno.appointment.starts_at.isoformat()[:16])
    assert otro.appointment.starts_at.isoformat()[:16] not in response.text


# ------------------------------------------------------------------ vigencia


async def test_token_vencido_responde_410_con_contacto_de_la_clinica(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    """El turno terminó hace 73 h (TTL 72 h desde `ends_at`)."""
    fin = AGENDA_NOW - timedelta(hours=73)
    managed = await make_managed(
        db_session, fin - timedelta(minutes=30), status=AppointmentStatus.CONFIRMED
    )

    response = await app_client.get(managed.url)

    assert response.status_code == 410
    assert response.json()["detail"] == "manage_link_expired"
    assert response.json()["clinic"]["name"] == managed.booking.clinic.name
    _assert_privado(response)


async def test_token_vigente_despues_del_turno_es_solo_lectura(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    """Terminó hace 2 h: 200 con el estado final y sin acciones habilitadas."""
    fin = AGENDA_NOW - timedelta(hours=2)
    managed = await make_managed(
        db_session, fin - timedelta(minutes=30), status=AppointmentStatus.CONFIRMED
    )

    response = await app_client.get(managed.url)

    assert response.status_code == 200
    acciones = response.json()["actions"]
    assert (acciones["can_confirm"], acciones["can_cancel"], acciones["can_reschedule"]) == (
        False,
        False,
        False,
    )


# ------------------------------------------------------------- vista mínima


async def test_vista_de_un_turno_pendiente_en_cinco_dias(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    managed = await make_managed(db_session, at(10, days=5))
    managed.booking.clinic.contact_phone = "+541155550100"
    await db_session.flush()

    cuerpo = (await app_client.get(managed.url)).json()

    assert cuerpo["clinic"] == {
        "name": managed.booking.clinic.name,
        "phone": "+541155550100",
        "timezone": "America/Argentina/Buenos_Aires",
        "slug": managed.booking.clinic.slug,
    }
    turno = cuerpo["appointment"]
    assert turno["patient_first_name"] == "María"
    assert turno["professional_display_name"] == managed.booking.professional.display_name
    assert turno["starts_at"] == at(10, days=5).isoformat()
    assert (turno["status"], turno["origin"], turno["is_overbooking"]) == (
        "pending",
        "online",
        False,
    )
    assert cuerpo["policy"] == {
        "cancellation_window_hours": 24,
        "cancellation_closes_at": at(10, days=4).isoformat(),
    }
    assert cuerpo["actions"] == {
        "can_confirm": True,
        "can_cancel": True,
        "can_reschedule": True,
        "blocked_reason": None,
    }
    assert (
        cuerpo["manage_token_expires_at"] == (at(10, 30, days=5) + timedelta(hours=72)).isoformat()
    )


async def test_la_vista_no_filtra_datos_internos(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    managed = await make_managed(db_session, at(10, days=5))

    crudo = (await app_client.get(managed.url)).text

    prohibidos = [
        str(managed.appointment.id),
        str(managed.patient.id),
        str(managed.booking.chair.id),
        str(managed.booking.professional.id),
        str(managed.booking.clinic.id),
        str(managed.patient.phone_e164),
        str(managed.patient.email),
        "Ficticia Prueba",
        "chair_id",
        "patient_id",
        managed.token,
    ]
    for valor in prohibidos:
        assert valor not in crudo, valor


async def test_turno_ya_iniciado_queda_bloqueado_por_pasado(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    managed = await make_managed(
        db_session, AGENDA_NOW - timedelta(minutes=10), status=AppointmentStatus.CONFIRMED
    )

    acciones = (await app_client.get(managed.url)).json()["actions"]

    assert acciones["blocked_reason"] == "past"
    assert not (acciones["can_confirm"] or acciones["can_cancel"] or acciones["can_reschedule"])


async def test_turno_cancelado_sin_acciones(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    from app.models import CancellationReason

    managed = await make_managed(
        db_session,
        at(10, days=5),
        status=AppointmentStatus.CANCELLED,
        cancelled_at=AGENDA_NOW,
        cancellation_reason=CancellationReason.PACIENTE,
    )

    cuerpo = (await app_client.get(managed.url)).json()

    assert cuerpo["appointment"]["status"] == "cancelled"
    assert cuerpo["actions"]["blocked_reason"] == "not_manageable"
    assert not cuerpo["actions"]["can_cancel"]


async def test_ventana_cerrada_deshabilita_cancelar_y_muestra_el_telefono(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    """Ventana 24 h y turno en 3 h: se deriva a la clínica; confirmar sigue posible."""
    managed = await make_managed(db_session, AGENDA_NOW + timedelta(hours=3))
    managed.booking.clinic.contact_phone = "+541155550100"
    await db_session.flush()

    cuerpo = (await app_client.get(managed.url)).json()

    assert cuerpo["actions"] == {
        "can_confirm": True,
        "can_cancel": False,
        "can_reschedule": False,
        "blocked_reason": "window_closed",
    }
    assert cuerpo["clinic"]["phone"] == "+541155550100"


async def test_la_vista_trae_el_catalogo_cerrado_de_motivos_en_orden(
    app_client: httpx.AsyncClient, db_session: AsyncSession, agenda_clock: MutableClock
) -> None:
    managed = await make_managed(db_session, at(10, days=5))

    opciones = (await app_client.get(managed.url)).json()["reason_options"]

    assert [o["value"] for o in opciones] == [
        "no_puedo_asistir",
        "enfermedad",
        "viaje",
        "problema_economico",
        "otro",
    ]
    assert all(isinstance(o["label"], str) and o["label"] for o in opciones)
