"""RBAC clínico (C-15, D4; spec `clinical/access-control` salvo auditoría). Postgres + Redis reales.

- Recepción: `403 forbidden_role` en **todos** los endpoints clínicos, sin filas ni eventos.
- Odontólogo: solo pacientes con al menos un turno suyo; fuera de alcance → `404` idéntico al de
  un paciente inexistente.
- Admin: lee toda la clínica; escribe solo con `professional_id` (`403 professional_required`).
- Cross-tenant: un UUID de otra clínica → `404` en cada recurso.
- Toda respuesta clínica (también los errores) lleva `Cache-Control: no-store`.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from app.core.settings import Settings
from app.models import ClinicalAccessEvent, ClinicalRecord
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tests.clinical_helpers import (
    ClinicScene,
    count_rows,
    make_clinic_scene,
    open_record,
    seed_catalog,
)

pytestmark = pytest.mark.integration

ZERO = "00000000-0000-0000-0000-000000000000"


@dataclass(frozen=True, slots=True)
class Endpoint:
    method: str
    path: str  # `{pid}` = paciente, `{rid}` = ficha, `{x}` = id de un recurso hijo
    json: dict[str, Any] | None = None
    files: bool = False


# Todos los endpoints clínicos de D10. Los ids hijos son inexistentes: a recepción el guard la
# corta antes de buscarlos.
ENDPOINTS: tuple[Endpoint, ...] = (
    Endpoint("GET", "/api/patients/{pid}/clinical-record"),
    Endpoint("POST", "/api/patients/{pid}/clinical-record"),
    Endpoint("GET", "/api/clinical-records/{rid}/access-log"),
    Endpoint("GET", "/api/clinical-records/{rid}/anamnesis"),
    Endpoint("GET", "/api/clinical-records/{rid}/anamnesis/versions"),
    Endpoint(
        "POST", "/api/clinical-records/{rid}/anamnesis", {"expected_version": 0, "answers": {}}
    ),
    Endpoint("GET", "/api/odontogram/conditions"),
    Endpoint("GET", "/api/clinical-records/{rid}/odontogram"),
    Endpoint("GET", "/api/clinical-records/{rid}/odontogram/teeth/36/history"),
    Endpoint(
        "POST",
        "/api/clinical-records/{rid}/odontogram/events",
        {"entries": [{"tooth": 36, "surface": "O", "condition_id": None}]},
    ),
    Endpoint("GET", "/api/clinical-records/{rid}/evolutions"),
    Endpoint("POST", "/api/clinical-records/{rid}/evolutions", {"body": "Evolución ficticia"}),
    Endpoint(
        "POST",
        "/api/clinical-records/{rid}/evolutions/{x}/corrections",
        {"reason": "Motivo ficticio largo", "body": "Texto ficticio"},
    ),
    Endpoint("GET", "/api/clinical-records/{rid}/attachments"),
    Endpoint("POST", "/api/clinical-records/{rid}/attachments", files=True),
    Endpoint("GET", "/api/clinical-records/{rid}/attachments/{x}/content"),
    Endpoint(
        "POST",
        "/api/clinical-records/{rid}/attachments/{x}/removal",
        {"reason": "Motivo ficticio de baja"},
    ),
    Endpoint("GET", "/api/clinical-records/{rid}/treatment-plans"),
    Endpoint(
        "POST",
        "/api/clinical-records/{rid}/treatment-plans",
        {
            "title": "Plan ficticio",
            "items": [
                {"phase": 1, "description": "Item ficticio", "quantity": 1, "unit_price_cents": 1}
            ],
        },
    ),
    Endpoint("GET", "/api/clinical-records/{rid}/treatment-plans/{x}"),
    Endpoint(
        "POST",
        "/api/clinical-records/{rid}/treatment-plans/{x}/versions",
        {
            "expected_version": 1,
            "items": [
                {"phase": 1, "description": "Item ficticio", "quantity": 1, "unit_price_cents": 1}
            ],
        },
    ),
    Endpoint(
        "POST",
        "/api/clinical-records/{rid}/treatment-plans/{x}/versions/1/decision",
        {"decision": "accepted"},
    ),
    Endpoint("GET", "/api/clinical-records/{rid}/treatment-plans/{x}/versions/1/pdf"),
)
WRITES = tuple(e for e in ENDPOINTS if e.method == "POST")
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


async def _call(
    client: httpx.AsyncClient,
    endpoint: Endpoint,
    headers: dict[str, str],
    *,
    pid: uuid.UUID | str,
    rid: uuid.UUID | str,
    x: uuid.UUID | str = ZERO,
) -> httpx.Response:
    path = endpoint.path.format(pid=pid, rid=rid, x=x)
    if endpoint.files:
        return await client.post(
            path,
            headers=headers,
            files={"file": ("rx.png", PNG, "image/png")},
            data={"kind": "xray"},
        )
    return await client.request(endpoint.method, path, headers=headers, json=endpoint.json)


@pytest.fixture()
async def scene(db_session: AsyncSession, redis_client: Redis, settings: Settings) -> ClinicScene:
    s = await make_clinic_scene(db_session, redis_client, settings)
    await seed_catalog(db_session, s.clinic)
    return s


def _ids(e: Endpoint) -> str:
    return f"{e.method} {e.path}"


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=_ids)
async def test_recepcion_recibe_403_sin_filas_ni_eventos(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    scene: ClinicScene,
    endpoint: Endpoint,
) -> None:
    rid = await open_record(app_client, scene)
    eventos_antes = await count_rows(db_session, ClinicalAccessEvent)

    respuesta = await _call(
        app_client, endpoint, scene.headers["recepcion"], pid=scene.patient.id, rid=rid
    )

    assert respuesta.status_code == 403
    assert respuesta.json()["detail"] == "forbidden_role"
    assert respuesta.headers["cache-control"] == "no-store"
    assert await count_rows(db_session, ClinicalAccessEvent) == eventos_antes
    assert await count_rows(db_session, ClinicalRecord) == 1


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=_ids)
async def test_sin_token_es_401(
    app_client: httpx.AsyncClient, scene: ClinicScene, endpoint: Endpoint
) -> None:
    respuesta = await _call(app_client, endpoint, {}, pid=scene.patient.id, rid=ZERO)

    assert respuesta.status_code == 401


async def test_odontologo_con_turno_propio_abre_y_lee(
    app_client: httpx.AsyncClient, scene: ClinicScene
) -> None:
    path = f"/api/patients/{scene.patient.id}/clinical-record"

    abierta = await app_client.post(path, headers=scene.headers["odontologo"])
    leida = await app_client.get(path, headers=scene.headers["odontologo"])

    assert abierta.status_code == 201
    assert leida.status_code == 200
    assert leida.json()["record_id"] == abierta.json()["record_id"]
    assert leida.headers["cache-control"] == "no-store"


async def test_odontologo_sin_relacion_recibe_404_identico_al_inexistente(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    await open_record(app_client, scene)
    eventos_antes = await count_rows(db_session, ClinicalAccessEvent)
    headers = scene.headers["odontologo_b"]

    ajeno = await app_client.get(
        f"/api/patients/{scene.patient.id}/clinical-record", headers=headers
    )
    inexistente = await app_client.get(
        f"/api/patients/{uuid.uuid4()}/clinical-record", headers=headers
    )
    abrir = await app_client.post(
        f"/api/patients/{scene.patient.id}/clinical-record", headers=headers
    )

    assert (ajeno.status_code, ajeno.json()) == (404, {"detail": "patient_not_found"})
    assert (inexistente.status_code, inexistente.json()) == (404, {"detail": "patient_not_found"})
    assert (abrir.status_code, abrir.json()) == (404, {"detail": "patient_not_found"})
    assert ajeno.headers["cache-control"] == "no-store"
    assert await count_rows(db_session, ClinicalAccessEvent) == eventos_antes


async def test_odontologo_b_si_accede_a_su_propio_paciente(
    app_client: httpx.AsyncClient, scene: ClinicScene
) -> None:
    respuesta = await app_client.post(
        f"/api/patients/{scene.patient_b.id}/clinical-record", headers=scene.headers["odontologo_b"]
    )

    assert respuesta.status_code == 201


@pytest.mark.parametrize("endpoint", WRITES, ids=_ids)
async def test_admin_sin_professional_id_no_escribe(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    scene: ClinicScene,
    endpoint: Endpoint,
) -> None:
    rid = await open_record(app_client, scene)
    eventos_antes = await count_rows(db_session, ClinicalAccessEvent)

    respuesta = await _call(
        app_client, endpoint, scene.headers["admin"], pid=scene.patient.id, rid=rid
    )

    assert (respuesta.status_code, respuesta.json()) == (403, {"detail": "professional_required"})
    assert await count_rows(db_session, ClinicalAccessEvent) == eventos_antes


async def test_admin_lee_toda_la_clinica_y_admin_que_atiende_escribe(
    app_client: httpx.AsyncClient, scene: ClinicScene
) -> None:
    abierta = await app_client.post(
        f"/api/patients/{scene.patient_b.id}/clinical-record", headers=scene.headers["admin_prof"]
    )
    leida = await app_client.get(
        f"/api/patients/{scene.patient_b.id}/clinical-record", headers=scene.headers["admin"]
    )

    assert abierta.status_code == 201
    assert leida.status_code == 200


async def test_la_bitacora_es_solo_del_admin(
    app_client: httpx.AsyncClient, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)
    path = f"/api/clinical-records/{rid}/access-log"

    odontologo = await app_client.get(path, headers=scene.headers["odontologo"])
    admin = await app_client.get(path, headers=scene.headers["admin"])

    assert (odontologo.status_code, odontologo.json()) == (403, {"detail": "forbidden_role"})
    assert admin.status_code == 200


@pytest.fixture()
async def other(db_session: AsyncSession, redis_client: Redis, settings: Settings) -> ClinicScene:
    s = await make_clinic_scene(db_session, redis_client, settings)
    await seed_catalog(db_session, s.clinic)
    return s


ChildFactory = Callable[[httpx.AsyncClient, ClinicScene, uuid.UUID], Any]


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=_ids)
async def test_un_id_de_otra_clinica_es_404(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    scene: ClinicScene,
    other: ClinicScene,
    endpoint: Endpoint,
) -> None:
    """La ficha y el paciente son de la clínica B; el principal (admin que atiende) es de la A."""
    rid_b = await open_record(app_client, other)
    eventos_antes = await count_rows(db_session, ClinicalAccessEvent)

    respuesta = await _call(
        app_client, endpoint, scene.headers["admin_prof"], pid=other.patient.id, rid=rid_b
    )

    if endpoint.path == "/api/odontogram/conditions":
        assert respuesta.status_code == 200
        assert await count_rows(db_session, ClinicalAccessEvent) == eventos_antes
        return
    assert respuesta.status_code == 404
    assert respuesta.headers["cache-control"] == "no-store"
    assert await count_rows(db_session, ClinicalAccessEvent) == eventos_antes
