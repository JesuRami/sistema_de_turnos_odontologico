"""Link de gestión firmado y sin estado (C-09, D9): segundo formato de credencial.

El motor de recordatorios no puede recuperar el token aleatorio (la base solo guarda su SHA-256) y
un turno de recepción no tiene token: el link del mensaje lleva `v1.` + id del turno firmado con
HMAC (`MANAGE_LINK_SECRET`). Se resuelve por el mismo endpoint con las mismas guardas que C-08.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest
from app.core.settings import Settings, get_settings
from app.models import AppointmentOrigin, AppointmentStatus
from app.modules.reminders.links import (
    ManageLinkDisabled,
    build_manage_url,
    sign_manage_token,
    verify_manage_token,
)
from fastapi import FastAPI
from pydantic import SecretStr
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tests.appointment_helpers import at, reload
from tests.booking_helpers import make_booking
from tests.conftest import AGENDA_NOW, MutableClock
from tests.factories import make_appointment, make_patient
from tests.manage_helpers import make_managed

pytestmark = pytest.mark.integration

SECRETO = "firma-de-links-solo-para-tests-32-bytes-ok"
OTRO_SECRETO = "otro-secreto-de-links-para-tests-32-bytes"


@pytest.fixture()
def firma(app_instance: FastAPI, settings: Settings) -> Settings:
    """Inyecta un `MANAGE_LINK_SECRET` conocido en la app y devuelve esos mismos settings."""
    con_secreto = settings.model_copy(update={"MANAGE_LINK_SECRET": SecretStr(SECRETO)})
    app_instance.dependency_overrides[get_settings] = lambda: con_secreto
    return con_secreto


def _token(turno_id: uuid.UUID, secreto: str = SECRETO) -> str:
    return sign_manage_token(secreto, turno_id)


async def _turno_de_recepcion(
    db_session: AsyncSession, starts_at: datetime, **extra: Any
) -> uuid.UUID:
    b = await make_booking(db_session)
    turno = await make_appointment(
        db_session,
        b.clinic,
        patient=await make_patient(db_session, b.clinic, full_name="Paciente Ficticio Dos"),
        professional=b.professional,
        chair=b.chair,
        starts_at=starts_at,
        origin=AppointmentOrigin.RECEPTION,
        **extra,
    )
    assert turno.manage_token_hash is None
    return turno.id


# ------------------------------------------------------------ unidad: firma y verificación


def test_firmar_y_verificar_es_un_ida_y_vuelta() -> None:
    turno_id = uuid.uuid4()

    token = sign_manage_token(SECRETO, turno_id)

    assert token.startswith("v1.") and len(token) == 46
    assert verify_manage_token(SECRETO, token) == turno_id
    assert sign_manage_token(SECRETO, turno_id) == token  # estable: reproducible en cada envío


def test_un_secreto_distinto_no_verifica() -> None:
    assert verify_manage_token(OTRO_SECRETO, _token(uuid.uuid4())) is None


@pytest.mark.parametrize(
    "roto",
    ["", "v1.", "v1.corto", "v2." + "A" * 43, "x" * 46, "v1." + "A" * 44, "v1." + "!" * 43],
)
def test_formatos_rotos_no_verifican(roto: str) -> None:
    assert verify_manage_token(SECRETO, roto) is None


def test_un_caracter_alterado_no_verifica() -> None:
    token = _token(uuid.uuid4())
    alterado = token[:-1] + ("A" if token[-1] != "A" else "B")

    assert verify_manage_token(SECRETO, alterado) is None


def test_una_variante_con_el_relleno_alterado_no_es_otra_credencial() -> None:
    """El último carácter lleva 2 bits de relleno: cambiarlos decodifica igual pero no vale."""
    alfabeto = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    for _ in range(20):
        token = _token(uuid.uuid4())
        variante = token[:-1] + alfabeto[alfabeto.index(token[-1]) ^ 1]
        assert variante != token
        assert verify_manage_token(SECRETO, token) is not None
        assert verify_manage_token(SECRETO, variante) is None


def test_la_firma_de_un_turno_no_sirve_para_otro() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    token_a, token_b = _token(a), _token(b)
    # id de B con la parte de firma de A
    mezclado = token_b[:25] + token_a[25:]

    assert verify_manage_token(SECRETO, mezclado) is None


def test_sin_secreto_no_se_firma_ni_se_verifica() -> None:
    with pytest.raises(ManageLinkDisabled):
        sign_manage_token("", uuid.uuid4())
    assert verify_manage_token("", "v1." + "A" * 43) is None


def test_la_url_usa_el_frontend_publico(settings: Settings) -> None:
    con = settings.model_copy(
        update={
            "MANAGE_LINK_SECRET": SecretStr(SECRETO),
            "FRONTEND_PUBLIC_URL": "https://turnos.example.com/",
        }
    )
    turno_id = uuid.uuid4()

    assert build_manage_url(con, turno_id) == f"https://turnos.example.com/g/{_token(turno_id)}"


# ------------------------------------------------------------------- API: resolución


async def test_el_token_firmado_de_un_turno_online_resuelve_su_vista(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    firma: Settings,
    agenda_clock: MutableClock,
) -> None:
    managed = await make_managed(db_session, at(10, days=7))

    response = await app_client.get(f"/api/manage/{_token(managed.appointment.id)}")

    assert response.status_code == 200, response.text
    assert response.json()["appointment"]["status"] == "pending"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"


async def test_el_token_firmado_de_un_turno_de_recepcion_resuelve_su_vista(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    firma: Settings,
    agenda_clock: MutableClock,
) -> None:
    turno_id = await _turno_de_recepcion(db_session, at(10, days=7))

    response = await app_client.get(f"/api/manage/{_token(turno_id)}")

    assert response.status_code == 200, response.text
    assert response.json()["appointment"]["origin"] == "reception"


async def test_el_token_aleatorio_de_c07_sigue_resolviendo(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    firma: Settings,
    agenda_clock: MutableClock,
) -> None:
    managed = await make_managed(db_session, at(10, days=7))

    response = await app_client.get(managed.url)

    assert response.status_code == 200, response.text


async def test_toda_credencial_invalida_responde_el_mismo_404(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    firma: Settings,
    agenda_clock: MutableClock,
) -> None:
    managed = await make_managed(db_session, at(10, days=7))
    valido = _token(managed.appointment.id)
    alterado = valido[:-1] + ("A" if valido[-1] != "A" else "B")
    otro = _token(uuid.uuid4())
    mezclado = _token(uuid.uuid4())[:25] + valido[25:]
    inexistente_bien_firmado = _token(uuid.uuid4())
    otro_secreto = _token(managed.appointment.id, OTRO_SECRETO)
    candidatos = [
        alterado,
        otro,
        mezclado,
        inexistente_bien_firmado,
        otro_secreto,
        "v2." + valido[3:],
    ]

    respuestas = [await app_client.get(f"/api/manage/{t}") for t in candidatos]

    assert {r.status_code for r in respuestas} == {404}
    cuerpos = {r.text for r in respuestas}
    assert cuerpos == {'{"detail":"manage_link_not_found"}'}
    desconocido = await app_client.get("/api/manage/" + "z" * 43)
    assert desconocido.text in cuerpos


async def test_el_ttl_aplica_igual_al_token_firmado(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    firma: Settings,
    agenda_clock: MutableClock,
) -> None:
    vencido = await make_managed(db_session, AGENDA_NOW - timedelta(hours=75))
    reciente = await make_managed(
        db_session,
        AGENDA_NOW - timedelta(hours=3),
        booking=vencido.booking,
        status=AppointmentStatus.CONFIRMED,
    )

    caducado = await app_client.get(f"/api/manage/{_token(vencido.appointment.id)}")
    vigente = await app_client.get(f"/api/manage/{_token(reciente.appointment.id)}")

    assert caducado.status_code == 410
    assert caducado.json()["detail"] == "manage_link_expired"
    assert vigente.status_code == 200
    assert vigente.json()["actions"] == {
        "can_confirm": False,
        "can_cancel": False,
        "can_reschedule": False,
        "blocked_reason": "past",
    }


async def test_confirmar_cancelar_y_reprogramar_con_el_token_firmado(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    firma: Settings,
    agenda_clock: MutableClock,
) -> None:
    primero = await make_managed(db_session, at(10, days=7))
    segundo = await make_managed(db_session, at(11, days=7), booking=primero.booking)
    reception_id = await _turno_de_recepcion(db_session, at(12, days=7))

    confirmar = await app_client.patch(
        f"/api/manage/{_token(primero.appointment.id)}", json={"action": "confirm"}
    )
    mover = await app_client.patch(
        f"/api/manage/{_token(segundo.appointment.id)}",
        json={"action": "reschedule", "starts_at": at(9, 30, days=7).isoformat()},
    )
    cancelar = await app_client.patch(
        f"/api/manage/{_token(reception_id)}", json={"action": "cancel", "reason": "viaje"}
    )

    assert (confirmar.status_code, mover.status_code, cancelar.status_code) == (200, 200, 200), (
        confirmar.text,
        mover.text,
        cancelar.text,
    )
    assert (await reload(db_session, primero.appointment.id)).status is AppointmentStatus.CONFIRMED
    assert (await reload(db_session, reception_id)).status is AppointmentStatus.CANCELLED


async def test_el_token_firmado_no_aparece_en_errores_ni_logs(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    firma: Settings,
    agenda_clock: MutableClock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    managed = await make_managed(db_session, at(10, days=7))
    token = _token(managed.appointment.id)

    errores = [
        await app_client.patch(
            f"/api/manage/{token}", json={"action": "cancel", "note": "x" * 201}
        ),
        await app_client.patch(f"/api/manage/{token}", json={"action": "volar"}),
        await app_client.get(f"/api/manage/{token[:-1]}A"),
    ]

    assert [r.status_code for r in errores] == [422, 422, 404]
    for respuesta in errores:
        assert token not in respuesta.text
    # Solo logs de la app: `httpx`/`httpcore` son el cliente de test pidiendo la URL.
    logs_app = " | ".join(
        r.getMessage() for r in caplog.records if not r.name.startswith(("httpx", "httpcore"))
    )
    assert token not in logs_app


async def test_el_cupo_por_token_usa_el_sha256_y_no_el_token_firmado(
    app_instance: FastAPI,
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    firma: Settings,
    agenda_clock: MutableClock,
) -> None:
    managed = await make_managed(db_session, at(10, days=7))
    token = _token(managed.appointment.id)
    app_instance.dependency_overrides[get_settings] = lambda: firma.model_copy(
        update={"MANAGE_READ_TOKEN_RATE_LIMIT": "1/60s"}
    )

    primera = await app_client.get(f"/api/manage/{token}")
    segunda = await app_client.get(f"/api/manage/{token}")

    assert (primera.status_code, segunda.status_code) == (200, 429)
    claves = [
        k.decode() if isinstance(k, bytes) else k for k in await redis_client.keys("rl:manage:*")
    ]
    huella = hashlib.sha256(token.encode()).hexdigest()
    assert any(huella in k for k in claves)
    assert not any(token in k for k in claves)
