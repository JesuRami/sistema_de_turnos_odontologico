"""Odontograma FDI (C-15, spec `clinical/odontogram`). Postgres + Redis reales, datos sintéticos.

Hallazgos como eventos append-only por lote (1–32), estado vigente derivado del historial
(`DISTINCT ON`), historial por pieza con cursor y vínculo opcional con la evolución.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from app.core.settings import Settings
from app.models import (
    ClinicalAccessEvent,
    ClinicalAction,
    ClinicalEvolution,
    EvolutionKind,
    OdontogramCondition,
    OdontogramEvent,
)
from app.modules.clinical.odontogram import OdontogramService
from app.modules.clinical.schemas import OdontogramBatch, OdontogramEntry
from app.modules.clinical.service import RecordService
from redis.asyncio import Redis
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.clinical_helpers import (
    ClinicScene,
    access_events,
    count_rows,
    make_clinic_scene,
    make_committed_scene,
    open_record,
    principal_of,
    seed_catalog,
)

pytestmark = pytest.mark.integration


@pytest.fixture()
async def scene(db_session: AsyncSession, redis_client: Redis, settings: Settings) -> ClinicScene:
    s = await make_clinic_scene(db_session, redis_client, settings)
    await seed_catalog(db_session, s.clinic)
    return s


async def _condiciones(session: AsyncSession, clinic_id: uuid.UUID) -> dict[str, uuid.UUID]:
    filas = (
        await session.execute(
            select(OdontogramCondition.code, OdontogramCondition.id).where(
                OdontogramCondition.clinic_id == clinic_id
            )
        )
    ).all()
    return {f.code: f.id for f in filas}


def _entrada(tooth: int, surface: str, condition: uuid.UUID | None, **extra: Any) -> dict[str, Any]:
    return {
        "tooth": tooth,
        "surface": surface,
        "condition_id": str(condition) if condition else None,
        **extra,
    }


async def _lote(
    client: httpx.AsyncClient,
    scene: ClinicScene,
    rid: uuid.UUID,
    entradas: list[dict[str, Any]],
    rol: str = "odontologo",
) -> httpx.Response:
    return await client.post(
        f"/api/clinical-records/{rid}/odontogram/events",
        json={"entries": entradas},
        headers=scene.headers[rol],
    )


async def _vigente(
    client: httpx.AsyncClient, scene: ClinicScene, rid: uuid.UUID, dentition: str = "permanent"
) -> dict[tuple[int, str], str | None]:
    cuerpo = (
        await client.get(
            f"/api/clinical-records/{rid}/odontogram",
            params={"dentition": dentition},
            headers=scene.headers["odontologo"],
        )
    ).json()
    return {
        (pieza["tooth"], cara["surface"]): cara["condition_code"]
        for pieza in cuerpo["teeth"]
        for cara in pieza["surfaces"]
    }


async def test_catalogo_sembrado_y_aislado(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    scene: ClinicScene,
    redis_client: Redis,
    settings: Settings,
) -> None:
    otra = await make_clinic_scene(db_session, redis_client, settings)
    await seed_catalog(db_session, otra.clinic)
    ajenos = set((await _condiciones(db_session, otra.clinic.id)).values())

    respuesta = await app_client.get(
        "/api/odontogram/conditions", headers=scene.headers["odontologo"]
    )

    assert respuesta.status_code == 200
    items = respuesta.json()["items"]
    assert len(items) == 11
    assert len({i["code"] for i in items}) == 11
    assert {i["id"] for i in items}.isdisjoint({str(a) for a in ajenos})
    assert {i["code"]: i["scope"] for i in items}["ausente"] == "tooth"


async def test_lote_de_cinco_caras(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)
    c = await _condiciones(db_session, scene.clinic.id)
    eventos = await count_rows(db_session, ClinicalAccessEvent)

    respuesta = await _lote(
        app_client,
        scene,
        rid,
        [_entrada(36, cara, c["caries"]) for cara in ("M", "D", "O", "V", "L")],
    )

    assert respuesta.status_code == 201
    items = respuesta.json()["items"]
    assert len(items) == 5
    assert {i["dentition"] for i in items} == {"permanent"}
    assert {i["professional_id"] for i in items} == {str(scene.professional.id)}
    assert await count_rows(db_session, OdontogramEvent) == 5
    assert await count_rows(db_session, ClinicalAccessEvent) == eventos + 1
    assert (await access_events(db_session))[-1].payload == {"entries": 5}


async def test_pieza_temporal_valida(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)
    c = await _condiciones(db_session, scene.clinic.id)

    respuesta = await _lote(app_client, scene, rid, [_entrada(55, "D", c["obturacion"])])

    assert respuesta.status_code == 201
    assert respuesta.json()["items"][0]["dentition"] == "deciduous"


async def test_lote_con_una_pieza_invalida_no_inserta_nada(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)
    c = await _condiciones(db_session, scene.clinic.id)
    entradas = [_entrada(t, "O", c["caries"]) for t in (16, 26, 36, 46)] + [
        _entrada(99, "O", c["caries"])
    ]

    respuesta = await _lote(app_client, scene, rid, entradas)

    assert respuesta.status_code == 422
    assert await count_rows(db_session, OdontogramEvent) == 0


@pytest.mark.parametrize("tooth", [19, 49, 56, 86, 0])
async def test_codigos_fuera_de_rango(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene, tooth: int
) -> None:
    rid = await open_record(app_client, scene)

    respuesta = await _lote(app_client, scene, rid, [_entrada(tooth, "O", None)])

    assert respuesta.status_code == 422
    assert await count_rows(db_session, OdontogramEvent) == 0


@pytest.mark.parametrize("cantidad", [0, 33])
async def test_lote_vacio_o_excedido(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene, cantidad: int
) -> None:
    rid = await open_record(app_client, scene)
    entradas = [
        _entrada(tooth, cara, None)
        for tooth in (11, 12, 13, 14, 15, 16, 17)
        for cara in ("M", "D", "O", "V", "L")
    ][:cantidad]

    respuesta = await _lote(app_client, scene, rid, entradas)

    assert respuesta.status_code == 422
    assert await count_rows(db_session, OdontogramEvent) == 0


async def test_lote_de_32_entradas_se_acepta(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)
    entradas = [
        _entrada(tooth, cara, None)
        for tooth in (11, 12, 13, 14, 15, 16, 17)
        for cara in ("M", "D", "O", "V", "L")
    ][:32]

    respuesta = await _lote(app_client, scene, rid, entradas)

    assert respuesta.status_code == 201
    assert await count_rows(db_session, OdontogramEvent) == 32


async def test_misma_cara_repetida_en_el_lote_es_422(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    """Desvío conservador: dos entradas de la misma (pieza, cara) en un lote serían ambiguas."""
    rid = await open_record(app_client, scene)
    c = await _condiciones(db_session, scene.clinic.id)

    respuesta = await _lote(
        app_client, scene, rid, [_entrada(36, "O", c["caries"]), _entrada(36, "O", None)]
    )

    assert (respuesta.status_code, respuesta.json()) == (422, {"detail": "duplicate_entry"})
    assert await count_rows(db_session, OdontogramEvent) == 0


async def test_estado_de_otra_clinica_o_inactivo(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    scene: ClinicScene,
    redis_client: Redis,
    settings: Settings,
) -> None:
    rid = await open_record(app_client, scene)
    otra = await make_clinic_scene(db_session, redis_client, settings)
    await seed_catalog(db_session, otra.clinic)
    ajena = (await _condiciones(db_session, otra.clinic.id))["caries"]
    propia = (await _condiciones(db_session, scene.clinic.id))["sellador"]
    await db_session.execute(
        update(OdontogramCondition).where(OdontogramCondition.id == propia).values(active=False)
    )

    de_otra = await _lote(app_client, scene, rid, [_entrada(36, "O", ajena)])
    inactiva = await _lote(app_client, scene, rid, [_entrada(36, "O", propia)])

    assert (de_otra.status_code, de_otra.json()) == (422, {"detail": "condition_not_found"})
    assert (inactiva.status_code, inactiva.json()) == (422, {"detail": "condition_inactive"})
    assert await count_rows(db_session, OdontogramEvent) == 0


@pytest.mark.parametrize(
    ("codigo", "cara"), [("ausente", "O"), ("corona", "M"), ("caries", "W"), ("obturacion", "W")]
)
async def test_alcance_del_estado(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    scene: ClinicScene,
    codigo: str,
    cara: str,
) -> None:
    rid = await open_record(app_client, scene)
    c = await _condiciones(db_session, scene.clinic.id)

    respuesta = await _lote(app_client, scene, rid, [_entrada(36, cara, c[codigo])])

    assert (respuesta.status_code, respuesta.json()) == (
        422,
        {"detail": "condition_scope_mismatch"},
    )


async def test_estado_de_pieza_completa_con_w_se_acepta(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)
    c = await _condiciones(db_session, scene.clinic.id)

    respuesta = await _lote(app_client, scene, rid, [_entrada(46, "W", c["ausente"])])

    assert respuesta.status_code == 201


@pytest.mark.parametrize(("largo", "estado"), [(500, 201), (501, 422)])
async def test_nota_acotada(
    app_client: httpx.AsyncClient, scene: ClinicScene, largo: int, estado: int
) -> None:
    rid = await open_record(app_client, scene)
    nota = "n" * largo

    respuesta = await _lote(app_client, scene, rid, [_entrada(36, "O", None, note=nota)])

    assert respuesta.status_code == estado
    if estado == 422:
        assert nota not in respuesta.text


async def test_la_ultima_entrada_gana_y_limpiar_tapa_el_estado(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)
    c = await _condiciones(db_session, scene.clinic.id)

    await _lote(app_client, scene, rid, [_entrada(36, "O", c["caries"])])
    await _lote(app_client, scene, rid, [_entrada(36, "O", c["obturacion"])])
    assert (await _vigente(app_client, scene, rid))[(36, "O")] == "obturacion"
    historial = (
        await app_client.get(
            f"/api/clinical-records/{rid}/odontogram/teeth/36/history",
            headers=scene.headers["odontologo"],
        )
    ).json()
    assert [i["condition_code"] for i in historial["items"]] == ["obturacion", "caries"]

    await _lote(app_client, scene, rid, [_entrada(36, "O", None)])
    vigente = await _vigente(app_client, scene, rid)
    historial = (
        await app_client.get(
            f"/api/clinical-records/{rid}/odontogram/teeth/36/history",
            headers=scene.headers["odontologo"],
        )
    ).json()

    assert vigente[(36, "O")] is None
    assert [i["condition_code"] for i in historial["items"]] == [None, "obturacion", "caries"]


async def test_lectura_auditada_sin_pii(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    """Escenario "Lectura auditada"."""
    rid = await open_record(app_client, scene)

    await _vigente(app_client, scene, rid)

    eventos = await access_events(db_session, action=ClinicalAction.ODONTOGRAM_READ)
    assert len(eventos) == 1
    assert eventos[0].record_id == rid
    assert eventos[0].actor_user_id == scene.users["odontologo"].id
    assert eventos[0].payload == {"dentition": "permanent"}


async def test_ficha_sin_hallazgos_trae_todas_las_caras_sin_estado(
    app_client: httpx.AsyncClient, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)

    vigente = await _vigente(app_client, scene, rid)

    assert len(vigente) == 32 * 6
    assert set(vigente.values()) == {None}


async def test_filtro_por_denticion(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)
    c = await _condiciones(db_session, scene.clinic.id)
    await _lote(
        app_client, scene, rid, [_entrada(36, "O", c["caries"]), _entrada(55, "D", c["caries"])]
    )

    temporal = await _vigente(app_client, scene, rid, "deciduous")

    assert len(temporal) == 20 * 6
    assert {k for k, v in temporal.items() if v} == {(55, "D")}


async def test_denticion_invalida_es_422(app_client: httpx.AsyncClient, scene: ClinicScene) -> None:
    rid = await open_record(app_client, scene)

    respuesta = await app_client.get(
        f"/api/clinical-records/{rid}/odontogram",
        params={"dentition": "mixta"},
        headers=scene.headers["odontologo"],
    )

    assert respuesta.status_code == 422


async def test_historial_con_cursor(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)
    c = await _condiciones(db_session, scene.clinic.id)
    for codigo in ("caries", "obturacion", "sellador"):
        await _lote(app_client, scene, rid, [_entrada(36, "O", c[codigo])])
    path = f"/api/clinical-records/{rid}/odontogram/teeth/36/history"
    headers = scene.headers["odontologo"]

    primera = (await app_client.get(path, params={"limit": 2}, headers=headers)).json()
    segunda = (
        await app_client.get(
            path, params={"limit": 2, "cursor": primera["next_cursor"]}, headers=headers
        )
    ).json()

    assert [i["condition_code"] for i in primera["items"]] == ["sellador", "obturacion"]
    assert [i["condition_code"] for i in segunda["items"]] == ["caries"]
    assert segunda["next_cursor"] is None
    assert primera["items"][0]["created_by_user_id"] == str(scene.users["odontologo"].id)


async def test_pieza_invalida_en_el_historial(
    app_client: httpx.AsyncClient, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)

    respuesta = await app_client.get(
        f"/api/clinical-records/{rid}/odontogram/teeth/99/history",
        headers=scene.headers["odontologo"],
    )

    assert respuesta.status_code == 422


async def _evolucion(session: AsyncSession, scene: ClinicScene, rid: uuid.UUID) -> uuid.UUID:
    evolucion = ClinicalEvolution(
        clinic_id=scene.clinic.id,
        record_id=rid,
        professional_id=scene.professional.id,
        created_by_user_id=scene.users["odontologo"].id,
        kind=EvolutionKind.ENTRY,
        body="Evolución sintética",
        signed_at=datetime.now(UTC),
        content_sha256="d" * 64,
    )
    session.add(evolucion)
    await session.flush()
    return evolucion.id


async def test_vinculo_con_evolucion_propia_y_ajena(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    rid = await open_record(app_client, scene)
    rid_b = await app_client.post(
        f"/api/patients/{scene.patient_b.id}/clinical-record", headers=scene.headers["admin_prof"]
    )
    propia = await _evolucion(db_session, scene, rid)
    ajena = await _evolucion(db_session, scene, uuid.UUID(rid_b.json()["record_id"]))

    ok = await _lote(app_client, scene, rid, [_entrada(36, "O", None, evolution_id=str(propia))])
    mal = await _lote(app_client, scene, rid, [_entrada(36, "O", None, evolution_id=str(ajena))])

    assert ok.status_code == 201
    assert ok.json()["items"][0]["evolution_id"] == str(propia)
    assert (mal.status_code, mal.json()) == (422, {"detail": "evolution_not_found"})


async def test_la_proyeccion_usa_el_indice(
    app_client: httpx.AsyncClient, db_session: AsyncSession, scene: ClinicScene
) -> None:
    from app.modules.clinical.odontogram import projection_statement

    rid = await open_record(app_client, scene)
    stmt = projection_statement(scene.clinic.id, rid, "permanent")
    compilado = stmt.compile(compile_kwargs={"literal_binds": True})
    await db_session.execute(text("SET LOCAL enable_seqscan = off"))

    plan = (await db_session.execute(text(f"EXPLAIN {compilado}"))).scalars().all()

    assert any("ix_odontogram_event_projection" in linea for linea in plan)


async def test_dos_escrituras_simultaneas_en_la_misma_cara(committed_engine: AsyncEngine) -> None:
    async with AsyncSession(committed_engine, expire_on_commit=False) as session:
        s = await make_committed_scene(session)
        codigos = await _condiciones(session, s.clinic_id)
    principal = principal_of(s.dentist)
    async with AsyncSession(committed_engine, expire_on_commit=False) as session:
        ficha = await RecordService(session, principal).open(s.patient_id)

    async def _registrar(codigo: str) -> None:
        async with AsyncSession(committed_engine, expire_on_commit=False) as session:
            await OdontogramService(session, principal).record_events(
                ficha.record_id,
                OdontogramBatch(
                    entries=[OdontogramEntry(tooth=36, surface="O", condition_id=codigos[codigo])]
                ),
            )

    await asyncio.gather(_registrar("caries"), _registrar("obturacion"))

    async with AsyncSession(committed_engine, expire_on_commit=False) as session:
        filas = (
            await session.execute(
                select(OdontogramEvent.condition_id).order_by(
                    OdontogramEvent.created_at.desc(), OdontogramEvent.id.desc()
                )
            )
        ).all()
        vigente = await OdontogramService(session, principal).current(ficha.record_id, "permanent")
    assert len(filas) == 2
    cara = next(c for p in vigente.teeth if p.tooth == 36 for c in p.surfaces if c.surface == "O")
    assert cara.condition_id == filas[0].condition_id
