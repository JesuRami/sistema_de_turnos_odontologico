"""US-011 CA-1: búsqueda y alta rápida de pacientes por el personal (C-05, spec core/patients).

Datos 100 % sintéticos (regla 13): nombres inventados, teléfonos del rango
ficticio +54 9 11 5550-xxxx y emails @example.com.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

import httpx
import pytest
from app.core.settings import Settings
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tests.agenda_helpers import make_staff
from tests.factories import make_clinic, make_patient, unique_phone_e164

pytestmark = pytest.mark.integration


def _nacional(e164: str) -> str:
    """`+5491155501234` → `011 15 5550-1234` (formato nacional AR)."""
    abonado = e164[-8:]
    return f"011 15 {abonado[:4]}-{abonado[4:]}"


# ------------------------------------------------------------------ búsqueda


@pytest.mark.parametrize("rol", ["admin", "recepcion"])
async def test_busqueda_por_nombre_aproximado(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    rol: str,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    buscada = await make_patient(db_session, staff.clinic, full_name="Ana Prueba Ejemplo")
    await make_patient(db_session, staff.clinic, full_name="Zenón Distinto Inventado")

    response = await app_client.get(
        "/api/patients", params={"q": "ana prueba"}, headers=staff.headers[rol]
    )

    assert response.status_code == 200
    ids = [p["id"] for p in response.json()["items"]]
    assert ids[0] == str(buscada.id)
    assert len(ids) == 1


async def test_busqueda_por_telefono_en_formato_nacional(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    telefono = unique_phone_e164()
    buscado = await make_patient(db_session, staff.clinic, phone_e164=telefono)
    familiar = await make_patient(
        db_session, staff.clinic, full_name="Familiar Ficticio Dos", phone_e164=telefono
    )

    response = await app_client.get(
        "/api/patients", params={"q": _nacional(telefono)}, headers=staff.headers["recepcion"]
    )

    assert response.status_code == 200
    body = response.json()["items"]
    assert {p["id"] for p in body} == {str(buscado.id), str(familiar.id)}
    assert body[0]["phone_e164"] == telefono


async def test_busqueda_excluye_archivados_y_otras_clinicas(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    otra = await make_clinic(db_session)
    await make_patient(db_session, otra, full_name="Ana Prueba Ejemplo")
    await make_patient(
        db_session,
        staff.clinic,
        full_name="Ana Prueba Ejemplo",
        archived_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    response = await app_client.get(
        "/api/patients", params={"q": "ana prueba"}, headers=staff.headers["admin"]
    )

    assert response.status_code == 200
    assert response.json()["items"] == []


async def test_busqueda_devuelve_como_maximo_20(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    for n in range(25):
        await make_patient(db_session, staff.clinic, full_name=f"Ana Prueba Ejemplo {n}")

    response = await app_client.get(
        "/api/patients", params={"q": "ana prueba ejemplo"}, headers=staff.headers["admin"]
    )

    assert response.status_code == 200
    assert len(response.json()["items"]) == 20


@pytest.mark.parametrize("q", ["an", "  a ", ""])
async def test_termino_demasiado_corto(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    q: str,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    response = await app_client.get(
        "/api/patients", params={"q": q}, headers=staff.headers["recepcion"]
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "query_too_short"


async def test_termino_demasiado_largo(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    response = await app_client.get(
        "/api/patients", params={"q": "x" * 101}, headers=staff.headers["recepcion"]
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "query_too_long"


@pytest.mark.parametrize(
    ("metodo", "ruta"), [("GET", "/api/patients?q=ana"), ("POST", "/api/patients")]
)
async def test_odontologo_no_accede_a_pacientes(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    metodo: str,
    ruta: str,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    response = await app_client.request(
        metodo,
        ruta,
        headers=staff.headers["odontologo"],
        json=(
            {"full_name": "Paciente Ficticio", "email": "ficticio@example.com"}
            if metodo == "POST"
            else None
        ),
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "forbidden_role"


async def test_sin_token_es_401(app_client: httpx.AsyncClient) -> None:
    response = await app_client.get("/api/patients", params={"q": "ana"})
    assert response.status_code == 401


# ---------------------------------------------------------------------- alta


async def test_alta_con_nombre_y_telefono_nacional(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    telefono = unique_phone_e164()

    response = await app_client.post(
        "/api/patients",
        json={"full_name": "  Bruno Ficticio Alta  ", "phone": _nacional(telefono)},
        headers=staff.headers["recepcion"],
    )

    assert response.status_code == 201
    body = response.json()
    assert body["phone_e164"] == telefono
    assert body["full_name"] == "Bruno Ficticio Alta"
    assert body["whatsapp_opt_in"] is False
    uuid.UUID(body["id"])


async def test_alta_solo_con_email_y_opt_in(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    response = await app_client.post(
        "/api/patients",
        json={
            "full_name": "Carla Ficticia Mail",
            "email": "Carla.Ficticia@Example.com",
            "whatsapp_opt_in": True,
            "dni": "00000001",
        },
        headers=staff.headers["admin"],
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "carla.ficticia@example.com"
    assert body["phone_e164"] is None
    assert body["whatsapp_opt_in"] is True


async def test_duplicado_exacto_con_otro_uso_de_mayusculas(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    telefono = unique_phone_e164()
    existente = await make_patient(
        db_session, staff.clinic, full_name="Delia Ficticia Duplicada", phone_e164=telefono
    )

    response = await app_client.post(
        "/api/patients",
        json={"full_name": "DELIA ficticia duplicada", "phone": telefono},
        headers=staff.headers["recepcion"],
    )

    assert response.status_code == 409
    body = response.json()
    assert body["detail"] == "patient_duplicate"
    assert body["patient_id"] == str(existente.id)


async def test_familia_que_comparte_telefono(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    telefono = unique_phone_e164()
    await make_patient(
        db_session, staff.clinic, full_name="Elsa Ficticia Madre", phone_e164=telefono
    )

    response = await app_client.post(
        "/api/patients",
        json={"full_name": "Elio Ficticio Hijo", "phone": telefono},
        headers=staff.headers["recepcion"],
    )

    assert response.status_code == 201


async def test_mismo_nombre_y_telefono_en_otra_clinica_no_es_duplicado(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    telefono = unique_phone_e164()
    otra = await make_clinic(db_session)
    await make_patient(db_session, otra, full_name="Fito Ficticio Otro", phone_e164=telefono)

    response = await app_client.post(
        "/api/patients",
        json={"full_name": "Fito Ficticio Otro", "phone": telefono},
        headers=staff.headers["recepcion"],
    )

    assert response.status_code == 201


@pytest.mark.parametrize(
    "body",
    [
        {"full_name": "Sin Contacto Ficticio"},
        {"full_name": "   ", "email": "blanco@example.com"},
        {"full_name": "Extra Ficticio", "email": "x@example.com", "clinic_id": str(uuid.uuid4())},
        {"full_name": "Extra Ficticio", "email": "x@example.com", "archived_at": None},
    ],
)
async def test_alta_invalida_es_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    body: dict[str, object],
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    response = await app_client.post("/api/patients", json=body, headers=staff.headers["admin"])
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("campo", "valor"),
    [("phone", "+54 9 11 5550 12ab"), ("email", "gina.ficticia.sin.arroba.example.com")],
)
async def test_errores_de_contacto_sin_datos_personales(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    caplog: pytest.LogCaptureFixture,
    campo: str,
    valor: str,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    caplog.set_level(logging.DEBUG)

    response = await app_client.post(
        "/api/patients",
        json={"full_name": "Gina Ficticia Error", campo: valor},
        headers=staff.headers["recepcion"],
    )

    assert response.status_code == 422
    for dato in (valor, "5550", "12ab", "gina.ficticia", "Gina Ficticia"):
        assert dato not in response.text
        assert dato not in caplog.text
