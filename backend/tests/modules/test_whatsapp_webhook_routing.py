"""Enrutamiento de una respuesta del paciente a clínica y turno (C-10, D7; spec whatsapp-webhook).

Se usa la intención `unknown` ("hola") para observar solo el enrutamiento: registra el entrante
sin tocar turnos ni encolar respuestas. Postgres real; datos ficticios (regla 13).
"""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta

import httpx
import pytest
from app.core.settings import Settings, get_settings
from app.models import (
    AppointmentOrigin,
    AppointmentStatus,
    Clinic,
    ReminderStatus,
    WhatsAppInbound,
)
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_appointment, make_clinic, make_patient
from tests.reminder_helpers import AHORA, Scene, make_job, make_scene
from tests.whatsapp_helpers import (
    SHARED_NUMBER,
    WEBHOOK,
    encode,
    envelope,
    signed_headers,
    text_message,
    whatsapp_settings,
)

pytestmark = pytest.mark.integration


@pytest.fixture()
def settings() -> Settings:
    return whatsapp_settings(Settings())  # type: ignore[call-arg]


@pytest.fixture(autouse=True)
def _config(app_instance: FastAPI, settings: Settings) -> None:
    app_instance.dependency_overrides[get_settings] = lambda: settings
    from app.common.clock import get_now

    app_instance.dependency_overrides[get_now] = lambda: AHORA


def _wamid() -> str:
    return "wamid.FICTICIO-" + secrets.token_hex(8)


def _numero_propio() -> str:
    return "2" + "".join(secrets.choice("0123456789") for _ in range(14))


def _wa(escena: Scene) -> str:
    telefono = escena.patient.phone_e164
    assert telefono is not None
    return telefono.removeprefix("+")


async def _post(
    client: httpx.AsyncClient,
    wa_id: str,
    texto: str = "hola",
    *,
    numero: str = SHARED_NUMBER,
    contexto: str | None = None,
    message_id: str | None = None,
) -> httpx.Response:
    mensaje = text_message(
        wa_id, texto, AHORA, message_id=message_id or _wamid(), context_id=contexto
    )
    cuerpo = encode(envelope(phone_number_id=numero, messages=[mensaje]))
    return await client.post(WEBHOOK, content=cuerpo, headers=signed_headers(cuerpo))


async def _entrantes(session: AsyncSession) -> list[WhatsAppInbound]:
    return list(
        (await session.execute(select(WhatsAppInbound).order_by(WhatsAppInbound.clinic_id)))
        .scalars()
        .all()
    )


async def _recordatorio_enviado(session: AsyncSession, escena: Scene) -> str:
    pid = _wamid()
    await make_job(
        session,
        escena.appointment,
        status=ReminderStatus.SENT,
        sent_at=AHORA,
        provider_message_id=pid,
    )
    return pid


async def _otro_turno_mismo_telefono(session: AsyncSession, escena: Scene, clinic: Clinic) -> Scene:
    """Ficha con el mismo teléfono en otra clínica, con su propio turno futuro."""
    otra = await make_scene(
        session,
        clinic=clinic,
        status=AppointmentStatus.PENDING,
        origin=AppointmentOrigin.ONLINE,
    )
    otra.patient.phone_e164 = escena.patient.phone_e164
    await session.flush()
    return otra


async def test_con_contexto_resuelve_el_turno_del_recordatorio(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    escena = await make_scene(db_session, opt_in=True)
    pid = await _recordatorio_enviado(db_session, escena)
    # Otro turno futuro del mismo paciente: sin contexto sería ambiguo.
    await make_appointment(
        db_session,
        escena.clinic,
        patient=escena.patient,
        professional=escena.professional,
        chair=escena.chair,
        starts_at=AHORA + timedelta(days=9),
    )

    assert (await _post(app_client, _wa(escena), contexto=pid)).status_code == 200

    [fila] = await _entrantes(db_session)
    assert (fila.clinic_id, fila.patient_id, fila.appointment_id, fila.routed_by) == (
        escena.clinic.id,
        escena.patient.id,
        escena.appointment.id,
        "context",
    )


async def test_contexto_de_otro_telefono_se_ignora_y_cae_a_telefono(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    ajena = await make_scene(db_session, opt_in=True)
    pid = await _recordatorio_enviado(db_session, ajena)
    propia = await make_scene(db_session, opt_in=True)

    await _post(app_client, _wa(propia), contexto=pid)

    [fila] = await _entrantes(db_session)
    assert (fila.patient_id, fila.appointment_id, fila.routed_by) == (
        propia.patient.id,
        propia.appointment.id,
        "phone",
    )


async def test_sin_contexto_con_un_solo_turno_lo_resuelve(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    escena = await make_scene(db_session, opt_in=True)

    await _post(app_client, _wa(escena))

    [fila] = await _entrantes(db_session)
    assert (fila.appointment_id, fila.routed_by, fila.phone_number_id) == (
        escena.appointment.id,
        "phone",
        SHARED_NUMBER,
    )


async def test_turnos_pasados_o_cancelados_no_son_candidatos(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    escena = await make_scene(db_session, opt_in=True)
    await make_appointment(
        db_session,
        escena.clinic,
        patient=escena.patient,
        professional=escena.professional,
        chair=escena.chair,
        starts_at=AHORA - timedelta(days=2),
    )

    await _post(app_client, _wa(escena))

    [fila] = await _entrantes(db_session)
    assert fila.appointment_id == escena.appointment.id


async def test_numero_compartido_con_dos_clinicas_es_ambiguo(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    escena = await make_scene(db_session, opt_in=True)
    otra = await _otro_turno_mismo_telefono(db_session, escena, await make_clinic(db_session))

    await _post(app_client, _wa(escena))

    filas = await _entrantes(db_session)
    assert {f.clinic_id for f in filas} == {escena.clinic.id, otra.clinic.id}
    assert all(f.appointment_id is None for f in filas)


async def test_numero_propio_solo_considera_su_clinica(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    propio = _numero_propio()
    clinica_a = await make_clinic(db_session, whatsapp_phone_number_id=propio)
    escena = await make_scene(db_session, clinic=clinica_a, opt_in=True)
    await _otro_turno_mismo_telefono(db_session, escena, await make_clinic(db_session))

    await _post(app_client, _wa(escena), numero=propio)

    [fila] = await _entrantes(db_session)
    assert (fila.clinic_id, fila.appointment_id) == (clinica_a.id, escena.appointment.id)


async def test_el_compartido_no_ve_clinicas_con_numero_propio(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    clinica = await make_clinic(db_session, whatsapp_phone_number_id=_numero_propio())
    escena = await make_scene(db_session, clinic=clinica, opt_in=True)

    await _post(app_client, _wa(escena), numero=SHARED_NUMBER)

    assert await _entrantes(db_session) == []


async def test_wa_id_argentino_sin_el_9_matchea(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    clinica = await make_clinic(db_session)
    paciente = await make_patient(db_session, clinica, phone_e164="+5491155550177")
    escena = await make_scene(db_session, clinic=clinica, opt_in=True)
    escena.appointment.patient_id = paciente.id
    await db_session.flush()

    await _post(app_client, "541155550177")

    [fila] = await _entrantes(db_session)
    assert fila.patient_id == paciente.id


async def test_remitente_desconocido_no_deja_rastro(
    app_client: httpx.AsyncClient, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)

    respuesta = await _post(app_client, "5491155550999")

    assert respuesta.status_code == 200
    assert await _entrantes(db_session) == []
    assert "whatsapp_inbound_unrouted" in caplog.text
    assert "5491155550999" not in caplog.text


async def test_numero_receptor_desconocido_no_deja_rastro(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    escena = await make_scene(db_session, opt_in=True)

    await _post(app_client, _wa(escena), numero="300000000000001")

    assert await _entrantes(db_session) == []


async def test_paciente_fusionado_no_es_candidato(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    escena = await make_scene(db_session, opt_in=True)
    conservado = await make_patient(db_session, escena.clinic)
    escena.patient.merged_into_patient_id = conservado.id
    escena.patient.archived_at = AHORA
    await db_session.flush()

    await _post(app_client, _wa(escena))

    assert await _entrantes(db_session) == []
