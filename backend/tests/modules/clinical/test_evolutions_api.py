"""Evoluciones firmadas e inmutables (C-15, D6, spec `clinical/evolutions`).

Postgres + Redis reales; las correcciones concurrentes usan commits reales. El hash se recalcula
acá con la regla canónica de D6 (claves ordenadas, UTF-8, `signed_at` UTC con microsegundos), sin
reutilizar el código del servicio.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from app.core.settings import Settings
from app.models import (
    AppointmentEvent,
    AppointmentStatus,
    ClinicalAccessEvent,
    ClinicalAction,
    ClinicalEvolution,
    EvolutionKind,
)
from app.modules.clinical.evolutions import EvolutionService, evolution_hash
from app.modules.clinical.schemas import CorrectionCreate, EvolutionCreate
from app.modules.clinical.service import RecordService
from redis.asyncio import Redis
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.clinical_helpers import (
    TEXTO_CLINICO,
    ClinicScene,
    access_events,
    count_rows,
    make_clinic_scene,
    make_committed_scene,
    open_record,
    principal_of,
)
from tests.factories import make_appointment

pytestmark = pytest.mark.integration


@pytest.fixture()
async def scene(db_session: AsyncSession, redis_client: Redis, settings: Settings) -> ClinicScene:
    return await make_clinic_scene(db_session, redis_client, settings)


def _hash_independiente(cuerpo: dict[str, Any]) -> str:
    firmado = datetime.fromisoformat(cuerpo["signed_at"]).astimezone(UTC)
    canonico = {
        "record_id": cuerpo["record_id"],
        "appointment_id": cuerpo["appointment_id"],
        "professional_id": cuerpo["professional_id"],
        "kind": cuerpo["kind"],
        "corrects_evolution_id": cuerpo["corrects_evolution_id"],
        "reason": cuerpo["reason"],
        "body": cuerpo["body"],
        "signed_at": firmado.isoformat(timespec="microseconds"),
    }
    crudo = json.dumps(canonico, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(crudo.encode("utf-8")).hexdigest()


async def _crear(
    client: httpx.AsyncClient,
    scene: ClinicScene,
    rid: uuid.UUID,
    rol: str = "odontologo",
    **cuerpo: Any,
) -> httpx.Response:
    datos = {"body": TEXTO_CLINICO, **cuerpo}
    return await client.post(
        f"/api/clinical-records/{rid}/evolutions", json=datos, headers=scene.headers[rol]
    )


async def _corregir(
    client: httpx.AsyncClient,
    scene: ClinicScene,
    rid: uuid.UUID,
    eid: str,
    rol: str = "odontologo",
    reason: str = "Corrección de dato sintético",
    body: str = "Texto corregido ficticio",
) -> httpx.Response:
    return await client.post(
        f"/api/clinical-records/{rid}/evolutions/{eid}/corrections",
        json={"reason": reason, "body": body},
        headers=scene.headers[rol],
    )


async def test_evolucion_creada_con_firma_simple(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)

    respuesta = await _crear(app_client, scene, rid, body=f"  {TEXTO_CLINICO}  ")

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["body"] == TEXTO_CLINICO
    assert cuerpo["professional_id"] == str(scene.professional.id)
    assert cuerpo["created_by_user_id"] == str(scene.users["odontologo"].id)
    assert cuerpo["kind"] == "entry"
    assert len(cuerpo["content_sha256"]) == 64
    assert cuerpo["content_sha256"] == _hash_independiente(cuerpo)
    assert (await access_events(db_session))[-1].action is ClinicalAction.EVOLUTION_WRITE


@pytest.mark.parametrize("body", ["   ", "x" * 4001, ""])
async def test_cuerpo_vacio_o_largo(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene, body: str
) -> None:
    rid = await open_record(app_client, scene)

    respuesta = await _crear(app_client, scene, rid, body=body)

    assert respuesta.status_code == 422
    assert await count_rows(db_session, ClinicalEvolution) == 0


async def test_cuerpo_de_4000_caracteres_se_acepta(
    app_client: httpx.AsyncClient, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)

    assert (await _crear(app_client, scene, rid, body="z" * 4000)).status_code == 201


@pytest.mark.parametrize(
    "extra",
    [{"signed_at": "2030-01-01T00:00:00Z"}, {"professional_id": str(uuid.uuid4())}],
    ids=["reloj_del_cliente", "autoria_ajena"],
)
async def test_campos_del_servidor_en_el_cuerpo_son_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    scene: ClinicScene,
    extra: dict[str, str],
) -> None:
    rid = await open_record(app_client, scene)

    respuesta = await _crear(app_client, scene, rid, **extra)

    assert respuesta.status_code == 422
    assert TEXTO_CLINICO not in respuesta.text
    assert "input" not in str([sorted(e) for e in respuesta.json()["detail"]])
    assert await count_rows(db_session, ClinicalEvolution) == 0


async def test_admin_que_atiende_firma_con_su_profesional(
    app_client: httpx.AsyncClient, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)

    respuesta = await _crear(app_client, scene, rid, "admin_prof")

    assert respuesta.status_code == 201
    assert respuesta.json()["professional_id"] == str(scene.professional.id)


async def test_vinculo_con_turno_propio(app_client: httpx.AsyncClient, scene: ClinicScene) -> None:
    rid = await open_record(app_client, scene)

    con = await _crear(app_client, scene, rid, appointment_id=str(scene.appointment.id))
    sin = await _crear(app_client, scene, rid)

    assert con.status_code == 201
    assert con.json()["appointment_id"] == str(scene.appointment.id)
    assert sin.json()["appointment_id"] is None


async def test_turno_de_otro_paciente_otro_profesional_u_otra_clinica(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    scene: ClinicScene,
    redis_client: Redis,
    settings: Settings,
) -> None:
    rid = await open_record(app_client, scene)
    de_otro_profesional = await make_appointment(
        db_session,
        scene.clinic,
        patient=scene.patient,
        professional=scene.professional_b,
        chair=scene.chair,
        starts_at=scene.appointment.starts_at + timedelta(days=1),
        created_by_user_id=scene.users["admin"].id,
    )
    otra = await make_clinic_scene(db_session, redis_client, settings)

    respuestas = [
        await _crear(app_client, scene, rid, appointment_id=str(turno))
        for turno in (scene.appointment_b.id, de_otro_profesional.id, otra.appointment.id)
    ]

    assert [(r.status_code, r.json()) for r in respuestas] == [
        (422, {"detail": "appointment_mismatch"})
    ] * 3
    assert await count_rows(db_session, ClinicalEvolution) == 0
    # El admin que atiende no está atado a su profesional para el vínculo (solo el odontólogo).
    admin = await _crear(
        app_client, scene, rid, "admin_prof", appointment_id=str(de_otro_profesional.id)
    )
    assert admin.status_code == 201


@pytest.mark.parametrize("estado", ["cancelled", "futuro"])
async def test_turno_cancelado_o_futuro_no_cambia_la_agenda(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene, estado: str
) -> None:
    if estado == "cancelled":
        await db_session.execute(
            text(
                "UPDATE appointment SET status = 'cancelled', cancelled_at = now(), "
                "cancellation_reason = 'clinica' WHERE id = :id"
            ),
            {"id": scene.appointment.id},
        )
    rid = await open_record(app_client, scene)
    eventos_turno = await count_rows(db_session, AppointmentEvent)

    respuesta = await _crear(app_client, scene, rid, appointment_id=str(scene.appointment.id))

    assert respuesta.status_code == 201
    assert await count_rows(db_session, AppointmentEvent) == eventos_turno
    status = await db_session.scalar(
        text("SELECT status::text FROM appointment WHERE id = :id"), {"id": scene.appointment.id}
    )
    esperado = AppointmentStatus.CANCELLED if estado == "cancelled" else AppointmentStatus.CONFIRMED
    assert status == esperado.value


async def test_el_autor_corrige_y_la_original_no_cambia(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)
    original = (await _crear(app_client, scene, rid)).json()

    respuesta = await _corregir(app_client, scene, rid, original["id"])

    assert respuesta.status_code == 201
    correccion = respuesta.json()
    assert correccion["kind"] == "correction"
    assert correccion["corrects_evolution_id"] == original["id"]
    assert correccion["reason"] == "Corrección de dato sintético"
    assert correccion["content_sha256"] == _hash_independiente(correccion)
    fila = (
        await db_session.execute(
            select(ClinicalEvolution.body, ClinicalEvolution.content_sha256).where(
                ClinicalEvolution.id == uuid.UUID(original["id"])
            )
        )
    ).one()
    assert (fila.body, fila.content_sha256) == (original["body"], original["content_sha256"])
    assert (await access_events(db_session))[-1].action is ClinicalAction.EVOLUTION_CORRECT


async def test_otro_odontologo_no_corrige(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    await make_appointment(
        db_session,
        scene.clinic,
        patient=scene.patient,
        professional=scene.professional_b,
        chair=scene.chair,
        starts_at=scene.appointment.starts_at + timedelta(days=2),
        created_by_user_id=scene.users["admin"].id,
    )
    rid = await open_record(app_client, scene)
    original = (await _crear(app_client, scene, rid)).json()

    respuesta = await _corregir(app_client, scene, rid, original["id"], "odontologo_b")

    assert (respuesta.status_code, respuesta.json()) == (403, {"detail": "not_evolution_author"})
    assert await count_rows(db_session, ClinicalEvolution) == 1


@pytest.mark.parametrize(("motivo", "estado"), [("x" * 9, 422), ("x" * 10, 201), ("x" * 301, 422)])
async def test_motivo_acotado(
    app_client: httpx.AsyncClient, scene: ClinicScene, motivo: str, estado: int
) -> None:
    rid = await open_record(app_client, scene)
    original = (await _crear(app_client, scene, rid)).json()

    respuesta = await _corregir(app_client, scene, rid, original["id"], reason=motivo)

    assert respuesta.status_code == estado


async def test_evolucion_de_otra_ficha_es_404(
    app_client: httpx.AsyncClient, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)
    rid_b = uuid.UUID(
        (
            await app_client.post(
                f"/api/patients/{scene.patient_b.id}/clinical-record",
                headers=scene.headers["admin_prof"],
            )
        ).json()["record_id"]
    )
    ajena = (await _crear(app_client, scene, rid_b, "admin_prof")).json()

    respuesta = await _corregir(app_client, scene, rid, ajena["id"])
    inexistente = await _corregir(app_client, scene, rid, str(uuid.uuid4()))

    assert (respuesta.status_code, respuesta.json()) == (404, {"detail": "evolution_not_found"})
    assert inexistente.json() == {"detail": "evolution_not_found"}


async def test_correccion_de_una_corregida_apunta_a_la_ultima(
    app_client: httpx.AsyncClient, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)
    original = (await _crear(app_client, scene, rid)).json()
    primera = (await _corregir(app_client, scene, rid, original["id"])).json()

    segunda = (await _corregir(app_client, scene, rid, original["id"])).json()

    assert segunda["corrects_evolution_id"] == primera["id"]


async def test_correcciones_concurrentes_quedan_ambas(committed_engine: AsyncEngine) -> None:
    async with AsyncSession(committed_engine, expire_on_commit=False) as session:
        s = await make_committed_scene(session)
    principal = principal_of(s.dentist)
    async with AsyncSession(committed_engine, expire_on_commit=False) as session:
        ficha = await RecordService(session, principal).open(s.patient_id)
        original = await EvolutionService(session, principal, datetime.now(UTC)).create(
            ficha.record_id, EvolutionCreate(body="Evolución sintética original")
        )

    async def _corregir_servicio(texto: str) -> uuid.UUID:
        async with AsyncSession(committed_engine, expire_on_commit=False) as session:
            creada = await EvolutionService(session, principal, datetime.now(UTC)).correct(
                ficha.record_id,
                original.id,
                CorrectionCreate(reason="Corrección concurrente ficticia", body=texto),
            )
            return creada.id

    ids = await asyncio.gather(_corregir_servicio("Texto A"), _corregir_servicio("Texto B"))

    assert len(set(ids)) == 2
    async with AsyncSession(committed_engine) as session:
        total = await session.scalar(
            select(func.count()).where(ClinicalEvolution.kind == EvolutionKind.CORRECTION)
        )
        assert total == 2


async def _sembrar(
    session: AsyncSession, scene: ClinicScene, rid: uuid.UUID, cantidad: int
) -> list[uuid.UUID]:
    base = datetime(2030, 1, 7, 12, 0, tzinfo=UTC)
    filas = [
        ClinicalEvolution(
            clinic_id=scene.clinic.id,
            record_id=rid,
            professional_id=scene.professional.id,
            created_by_user_id=scene.users["odontologo"].id,
            kind=EvolutionKind.ENTRY,
            body=f"Evolución sintética {n}",
            signed_at=base + timedelta(minutes=n),
            content_sha256="e" * 64,
        )
        for n in range(cantidad)
    ]
    session.add_all(filas)
    await session.flush()
    return [f.id for f in filas]


async def test_listado_paginado(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)
    ids = await _sembrar(db_session, scene, rid, 130)
    path = f"/api/clinical-records/{rid}/evolutions"
    headers = scene.headers["odontologo"]

    primera = (await app_client.get(path, params={"limit": 100}, headers=headers)).json()
    segunda = (
        await app_client.get(
            path, params={"limit": 100, "cursor": primera["next_cursor"]}, headers=headers
        )
    ).json()

    assert len(primera["items"]) == 100
    assert primera["items"][0]["id"] == str(ids[-1])
    assert len(segunda["items"]) == 30
    assert segunda["next_cursor"] is None
    assert segunda["items"][-1]["id"] == str(ids[0])


async def test_la_original_corregida_se_marca(
    app_client: httpx.AsyncClient, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)
    original = (await _crear(app_client, scene, rid)).json()
    correccion = (await _corregir(app_client, scene, rid, original["id"])).json()

    items = (
        await app_client.get(
            f"/api/clinical-records/{rid}/evolutions", headers=scene.headers["odontologo"]
        )
    ).json()["items"]
    por_id = {i["id"]: i for i in items}

    assert por_id[original["id"]]["corrected_by"] == correccion["id"]
    assert por_id[original["id"]]["body"] == TEXTO_CLINICO
    assert por_id[correccion["id"]]["corrected_by"] is None


async def test_filtro_por_turno(app_client: httpx.AsyncClient, scene: ClinicScene) -> None:
    rid = await open_record(app_client, scene)
    ligada = (await _crear(app_client, scene, rid, appointment_id=str(scene.appointment.id))).json()
    await _crear(app_client, scene, rid)

    items = (
        await app_client.get(
            f"/api/clinical-records/{rid}/evolutions",
            params={"appointment_id": str(scene.appointment.id)},
            headers=scene.headers["odontologo"],
        )
    ).json()["items"]

    assert [i["id"] for i in items] == [ligada["id"]]


@pytest.mark.parametrize("limit", [0, 101])
async def test_limite_invalido(
    app_client: httpx.AsyncClient, scene: ClinicScene, limit: int
) -> None:
    rid = await open_record(app_client, scene)

    respuesta = await app_client.get(
        f"/api/clinical-records/{rid}/evolutions",
        params={"limit": limit},
        headers=scene.headers["odontologo"],
    )

    assert respuesta.status_code == 422


async def test_falla_de_auditoria_revierte_la_evolucion(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    """Escenario "Falla de auditoría revierte la operación" sobre `POST` de evolución."""
    rid = await open_record(app_client, scene)
    await db_session.execute(
        text(
            "CREATE FUNCTION test_falla_evolucion() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN RAISE EXCEPTION 'falla inyectada'; END; $$"
        )
    )
    await db_session.execute(
        text(
            "CREATE TRIGGER trg_test_falla_evolucion BEFORE INSERT ON clinical_access_event "
            "FOR EACH ROW EXECUTE FUNCTION test_falla_evolucion()"
        )
    )

    respuesta = await _crear(app_client, scene, rid)
    await db_session.rollback()

    assert (respuesta.status_code, respuesta.json()["detail"]) == (500, "internal_error")
    assert await count_rows(db_session, ClinicalEvolution) == 0


def test_hash_canonico_determinista() -> None:
    campos: dict[str, Any] = {
        "record_id": uuid.UUID(int=1),
        "appointment_id": None,
        "professional_id": uuid.UUID(int=2),
        "kind": EvolutionKind.ENTRY,
        "corrects_evolution_id": None,
        "reason": None,
        "body": "Texto sintético con acentos: ñandú",
        "signed_at": datetime(2030, 1, 7, 11, 0, 0, 123456, tzinfo=UTC),
    }

    a = evolution_hash(**campos)
    b = evolution_hash(**campos)
    otro = evolution_hash(**{**campos, "body": "Texto sintético distinto"})

    assert a == b
    assert a != otro
    assert len(a) == 64
    esperado = _hash_independiente(
        {
            **{k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in campos.items()},
            "kind": "entry",
            "signed_at": campos["signed_at"].isoformat(),
        }
    )
    assert a == esperado


async def test_lista_auditada(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)
    antes = await count_rows(db_session, ClinicalAccessEvent)

    await app_client.get(f"/api/clinical-records/{rid}/evolutions", headers=scene.headers["admin"])

    assert await count_rows(db_session, ClinicalAccessEvent) == antes + 1
    assert (await access_events(db_session))[-1].action is ClinicalAction.EVOLUTION_READ
