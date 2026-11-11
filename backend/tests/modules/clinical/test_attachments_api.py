"""Adjuntos clínicos (C-15, D7, spec `clinical/attachments`). Postgres + Redis reales.

El almacenamiento es el de disco real sobre un directorio temporal (o un doble que falla, para la
ruta de error); la base nunca se reemplaza (regla 9). Archivos sintéticos.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from pathlib import Path

import httpx
import pytest
from app.common.exceptions import DomainError
from app.core.settings import Settings
from app.models import (
    AttachmentKind,
    ClinicalAccessEvent,
    ClinicalAction,
    ClinicalAttachment,
    ClinicalAttachmentRemoval,
)
from app.modules.clinical.attachments import AttachmentService, get_attachment_storage
from app.modules.clinical.schemas import RemovalCreate
from app.modules.clinical.service import RecordService
from app.modules.clinical.storage.base import AttachmentStorage
from app.modules.clinical.storage.local import LocalAttachmentStorage
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.clinical_helpers import (
    ClinicScene,
    access_events,
    count_rows,
    make_clinic_scene,
    make_committed_scene,
    open_record,
    principal_of,
)
from tests.clinical_storage import FailingAttachmentStorage

pytestmark = pytest.mark.integration

PNG = b"\x89PNG\r\n\x1a\n"
JPEG = b"\xff\xd8\xff\xe0"
PDF = b"%PDF-1.4\n"
MAX = 10 * 1024 * 1024


def _png(total: int) -> bytes:
    return PNG + b"\x00" * (total - len(PNG))


@pytest.fixture()
def storage(app_instance: FastAPI, tmp_path: Path) -> LocalAttachmentStorage:
    disco = LocalAttachmentStorage(tmp_path / "clinical_files")
    app_instance.dependency_overrides[get_attachment_storage] = lambda: disco
    return disco


@pytest.fixture()
async def scene(db_session: AsyncSession, redis_client: Redis, settings: Settings) -> ClinicScene:
    return await make_clinic_scene(db_session, redis_client, settings)


def _objetos(storage: LocalAttachmentStorage) -> list[Path]:
    return [p for p in storage.root.rglob("*") if p.is_file()] if storage.root.exists() else []


async def _subir(
    client: httpx.AsyncClient,
    scene: ClinicScene,
    rid: uuid.UUID,
    contenido: bytes,
    *,
    nombre: str = "rx.png",
    tipo: str = "image/png",
    kind: str = "xray",
    rol: str = "odontologo",
    evolution_id: str | None = None,
) -> httpx.Response:
    datos = {"kind": kind}
    if evolution_id:
        datos["evolution_id"] = evolution_id
    return await client.post(
        f"/api/clinical-records/{rid}/attachments",
        files={"file": (nombre, contenido, tipo)},
        data=datos,
        headers=scene.headers[rol],
    )


async def test_subida_valida(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    scene: ClinicScene,
    storage: LocalAttachmentStorage,
) -> None:
    rid = await open_record(app_client, scene)
    contenido = _png(204800)

    respuesta = await _subir(app_client, scene, rid, contenido)

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["size_bytes"] == 204800
    assert cuerpo["sha256"] == hashlib.sha256(contenido).hexdigest()
    assert (cuerpo["kind"], cuerpo["content_type"]) == ("xray", "image/png")
    assert "storage_key" not in cuerpo
    clave = await db_session.scalar(select(ClinicalAttachment.storage_key))
    assert clave is not None and clave.startswith(f"{scene.clinic.id}/")
    assert await storage.exists(clave)
    assert (await access_events(db_session))[-1].action is ClinicalAction.ATTACHMENT_UPLOAD


@pytest.mark.parametrize(
    ("contenido", "tipo"), [(JPEG + b"jpg", "image/jpeg"), (PDF + b"pdf", "application/pdf")]
)
async def test_tipo_por_contenido(
    app_client: httpx.AsyncClient,
    scene: ClinicScene,
    storage: LocalAttachmentStorage,
    contenido: bytes,
    tipo: str,
) -> None:
    rid = await open_record(app_client, scene)

    respuesta = await _subir(
        app_client, scene, rid, contenido, nombre="documento.bin", tipo="application/octet-stream"
    )

    assert respuesta.status_code == 201
    assert respuesta.json()["content_type"] == tipo


async def test_tipo_declarado_falso(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    scene: ClinicScene,
    storage: LocalAttachmentStorage,
) -> None:
    rid = await open_record(app_client, scene)

    respuesta = await _subir(app_client, scene, rid, b"MZ\x90\x00ejecutable-ficticio")

    assert (respuesta.status_code, respuesta.json()) == (415, {"detail": "unsupported_media_type"})
    assert await count_rows(db_session, ClinicalAttachment) == 0
    assert _objetos(storage) == []


async def test_archivo_demasiado_grande(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    scene: ClinicScene,
    storage: LocalAttachmentStorage,
) -> None:
    rid = await open_record(app_client, scene)

    respuesta = await _subir(app_client, scene, rid, _png(MAX + 1))

    assert (respuesta.status_code, respuesta.json()) == (413, {"detail": "attachment_too_large"})
    assert await count_rows(db_session, ClinicalAttachment) == 0
    assert _objetos(storage) == []


async def test_archivo_de_10_mib_justos_se_acepta(
    app_client: httpx.AsyncClient, scene: ClinicScene, storage: LocalAttachmentStorage
) -> None:
    rid = await open_record(app_client, scene)

    respuesta = await _subir(app_client, scene, rid, _png(MAX))

    assert respuesta.status_code == 201
    assert respuesta.json()["size_bytes"] == MAX


async def test_archivo_vacio(
    app_client: httpx.AsyncClient, scene: ClinicScene, storage: LocalAttachmentStorage
) -> None:
    rid = await open_record(app_client, scene)

    respuesta = await _subir(app_client, scene, rid, b"")

    assert (respuesta.status_code, respuesta.json()) == (422, {"detail": "attachment_empty"})


async def test_nombre_malicioso_se_sanea(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    scene: ClinicScene,
    storage: LocalAttachmentStorage,
) -> None:
    rid = await open_record(app_client, scene)

    respuesta = await _subir(app_client, scene, rid, _png(64), nombre="../../etc/passwd\n.png")

    assert respuesta.status_code == 201
    nombre = respuesta.json()["display_name"]
    # httpx codifica el salto de línea como `%0A` en el multipart: sin ruta ni control.
    assert nombre.startswith("passwd") and nombre.endswith(".png")
    assert "/" not in nombre and chr(10) not in nombre and ".." not in nombre
    clave = await db_session.scalar(select(ClinicalAttachment.storage_key))
    assert clave is not None and "passwd" not in clave and ".." not in clave


async def _sembrar_adjuntos(
    session: AsyncSession, scene: ClinicScene, rid: uuid.UUID, cantidad: int
) -> list[ClinicalAttachment]:
    filas = [
        ClinicalAttachment(
            clinic_id=scene.clinic.id,
            record_id=rid,
            kind=AttachmentKind.PHOTO,
            content_type="image/png",
            size_bytes=10,
            sha256="f" * 64,
            display_name=f"foto-{n}.png",
            storage_key=f"{scene.clinic.id}/{uuid.uuid4().hex}",
            created_by_user_id=scene.users["odontologo"].id,
        )
        for n in range(cantidad)
    ]
    session.add_all(filas)
    await session.flush()
    return filas


async def test_tope_de_200_adjuntos_activos(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    scene: ClinicScene,
    storage: LocalAttachmentStorage,
) -> None:
    rid = await open_record(app_client, scene)
    filas = await _sembrar_adjuntos(db_session, scene, rid, 200)

    lleno = await _subir(app_client, scene, rid, _png(64))
    db_session.add(
        ClinicalAttachmentRemoval(
            clinic_id=scene.clinic.id,
            attachment_id=filas[0].id,
            reason="Motivo ficticio de baja",
            removed_by_user_id=scene.users["odontologo"].id,
        )
    )
    await db_session.flush()
    con_lugar = await _subir(app_client, scene, rid, _png(64))

    assert (lleno.status_code, lleno.json()) == (409, {"detail": "attachment_limit_reached"})
    assert con_lugar.status_code == 201


async def test_falla_del_almacenamiento_no_deja_fila(
    app_client: httpx.AsyncClient,
    app_instance: FastAPI,
    db_session: AsyncSession,
    scene: ClinicScene,
) -> None:
    app_instance.dependency_overrides[get_attachment_storage] = FailingAttachmentStorage
    rid = await open_record(app_client, scene)

    respuesta = await _subir(app_client, scene, rid, _png(64))
    await db_session.rollback()

    assert respuesta.status_code == 500
    assert respuesta.json()["detail"] == "internal_error"
    assert "disco" not in respuesta.text
    assert await count_rows(db_session, ClinicalAttachment) == 0


async def test_si_falla_la_base_se_quita_el_archivo_huerfano(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    scene: ClinicScene,
    storage: LocalAttachmentStorage,
) -> None:
    rid = await open_record(app_client, scene)
    await db_session.execute(
        text(
            "CREATE FUNCTION test_falla_adjunto() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN RAISE EXCEPTION 'falla inyectada'; END; $$"
        )
    )
    await db_session.execute(
        text(
            "CREATE TRIGGER trg_test_falla_adjunto BEFORE INSERT ON clinical_access_event "
            "FOR EACH ROW EXECUTE FUNCTION test_falla_adjunto()"
        )
    )

    respuesta = await _subir(app_client, scene, rid, _png(64))
    await db_session.rollback()

    assert respuesta.status_code == 500
    assert await count_rows(db_session, ClinicalAttachment) == 0
    assert _objetos(storage) == []


async def test_evolucion_ajena(
    app_client: httpx.AsyncClient, scene: ClinicScene, storage: LocalAttachmentStorage
) -> None:
    rid = await open_record(app_client, scene)

    respuesta = await _subir(app_client, scene, rid, _png(64), evolution_id=str(uuid.uuid4()))

    assert (respuesta.status_code, respuesta.json()) == (422, {"detail": "evolution_not_found"})
    assert _objetos(storage) == []


async def test_descarga_con_headers_seguros_y_bytes_identicos(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    scene: ClinicScene,
    storage: LocalAttachmentStorage,
) -> None:
    rid = await open_record(app_client, scene)
    contenido = _png(150_000)
    aid = (await _subir(app_client, scene, rid, contenido, nombre="radiografía ñ.png")).json()["id"]

    respuesta = await app_client.get(
        f"/api/clinical-records/{rid}/attachments/{aid}/content",
        headers=scene.headers["odontologo"],
    )

    assert respuesta.status_code == 200
    assert hashlib.sha256(respuesta.content).hexdigest() == hashlib.sha256(contenido).hexdigest()
    assert respuesta.headers["content-type"] == "image/png"
    assert respuesta.headers["content-disposition"].startswith("attachment;")
    assert (
        "filename*=UTF-8''radiograf%C3%ADa%20%C3%B1.png" in respuesta.headers["content-disposition"]
    )
    assert respuesta.headers["x-content-type-options"] == "nosniff"
    assert respuesta.headers["cache-control"] == "no-store"
    descarga = (await access_events(db_session, action=ClinicalAction.ATTACHMENT_DOWNLOAD))[0]
    assert str(descarga.object_id) == aid


async def test_adjunto_de_otra_clinica_es_404(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    scene: ClinicScene,
    storage: LocalAttachmentStorage,
    redis_client: Redis,
    settings: Settings,
) -> None:
    otra = await make_clinic_scene(db_session, redis_client, settings)
    rid_b = await open_record(app_client, otra)
    aid_b = (await _subir(app_client, otra, rid_b, _png(64))).json()["id"]
    rid = await open_record(app_client, scene)

    respuesta = await app_client.get(
        f"/api/clinical-records/{rid}/attachments/{aid_b}/content",
        headers=scene.headers["odontologo"],
    )

    assert (respuesta.status_code, respuesta.json()) == (404, {"detail": "attachment_not_found"})


async def test_objeto_ausente_es_500_sin_ruta(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    scene: ClinicScene,
    storage: LocalAttachmentStorage,
    caplog: pytest.LogCaptureFixture,
) -> None:
    rid = await open_record(app_client, scene)
    aid = (await _subir(app_client, scene, rid, _png(64))).json()["id"]
    for archivo in _objetos(storage):
        archivo.unlink()
    eventos = await count_rows(db_session, ClinicalAccessEvent)

    with caplog.at_level(logging.INFO):
        respuesta = await app_client.get(
            f"/api/clinical-records/{rid}/attachments/{aid}/content",
            headers=scene.headers["odontologo"],
        )

    assert respuesta.status_code == 500
    assert respuesta.json()["detail"] == "internal_error"
    assert str(storage.root) not in respuesta.text
    assert str(scene.clinic.id) not in respuesta.text
    assert any("attachment_object_missing" in r.getMessage() for r in caplog.records)
    assert not any(str(storage.root) in r.getMessage() for r in caplog.records)
    assert await count_rows(db_session, ClinicalAccessEvent) == eventos


async def _baja(
    client: httpx.AsyncClient,
    scene: ClinicScene,
    rid: uuid.UUID,
    aid: str,
    reason: str = "Archivo cargado por error",
) -> httpx.Response:
    return await client.post(
        f"/api/clinical-records/{rid}/attachments/{aid}/removal",
        json={"reason": reason},
        headers=scene.headers["odontologo"],
    )


async def test_baja_logica_y_repetida(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    scene: ClinicScene,
    storage: LocalAttachmentStorage,
) -> None:
    rid = await open_record(app_client, scene)
    aid = (await _subir(app_client, scene, rid, _png(64))).json()["id"]

    primera = await _baja(app_client, scene, rid, aid)
    segunda = await _baja(app_client, scene, rid, aid)

    assert primera.status_code == 201
    assert (segunda.status_code, segunda.json()) == (409, {"detail": "attachment_already_removed"})
    assert await count_rows(db_session, ClinicalAttachmentRemoval) == 1
    assert await count_rows(db_session, ClinicalAttachment) == 1
    assert len(_objetos(storage)) == 1
    assert (await access_events(db_session, action=ClinicalAction.ATTACHMENT_REMOVE))[0].object_id
    corto = await _baja(app_client, scene, rid, aid, reason="corto")
    assert corto.status_code == 422


async def test_descarga_de_un_adjunto_dado_de_baja(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    scene: ClinicScene,
    storage: LocalAttachmentStorage,
) -> None:
    rid = await open_record(app_client, scene)
    aid = (await _subir(app_client, scene, rid, _png(64))).json()["id"]
    await _baja(app_client, scene, rid, aid)
    path = f"/api/clinical-records/{rid}/attachments/{aid}/content"

    odontologo = await app_client.get(path, headers=scene.headers["odontologo"])
    admin = await app_client.get(path, headers=scene.headers["admin"])

    assert odontologo.status_code == 404
    assert admin.status_code == 200
    descargas = await access_events(db_session, action=ClinicalAction.ATTACHMENT_DOWNLOAD)
    assert [e.actor_user_id for e in descargas] == [scene.users["admin"].id]


async def test_listados(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    scene: ClinicScene,
    storage: LocalAttachmentStorage,
) -> None:
    rid = await open_record(app_client, scene)
    ids = [
        (await _subir(app_client, scene, rid, _png(64), nombre=f"foto-{n}.png")).json()["id"]
        for n in range(4)
    ]
    await _baja(app_client, scene, rid, ids[0])
    path = f"/api/clinical-records/{rid}/attachments"

    activos = (await app_client.get(path, headers=scene.headers["odontologo"])).json()
    con_bajas = (
        await app_client.get(
            path, params={"include_removed": "true"}, headers=scene.headers["admin"]
        )
    ).json()
    prohibido = await app_client.get(
        path, params={"include_removed": "true"}, headers=scene.headers["odontologo"]
    )
    pagina = (
        await app_client.get(path, params={"limit": 2}, headers=scene.headers["odontologo"])
    ).json()

    assert [i["id"] for i in activos["items"]] == ids[:0:-1]
    assert all("storage_key" not in i for i in activos["items"])
    assert {"id", "kind", "display_name", "size_bytes"} <= set(activos["items"][0])
    assert len(con_bajas["items"]) == 4
    baja = next(i for i in con_bajas["items"] if i["id"] == ids[0])
    assert (baja["removed"], baja["removal_reason"]) == (True, "Archivo cargado por error")
    assert (prohibido.status_code, prohibido.json()) == (403, {"detail": "forbidden_role"})
    assert len(pagina["items"]) == 2 and pagina["next_cursor"] is not None


async def test_bajas_simultaneas(committed_engine: AsyncEngine, tmp_path: Path) -> None:
    async with AsyncSession(committed_engine, expire_on_commit=False) as session:
        s = await make_committed_scene(session)
    principal = principal_of(s.dentist)
    storage: AttachmentStorage = LocalAttachmentStorage(tmp_path)
    async with AsyncSession(committed_engine, expire_on_commit=False) as session:
        ficha = await RecordService(session, principal).open(s.patient_id)
        adjunto = ClinicalAttachment(
            clinic_id=s.clinic_id,
            record_id=ficha.record_id,
            kind=AttachmentKind.PHOTO,
            content_type="image/png",
            size_bytes=10,
            sha256="f" * 64,
            display_name="foto.png",
            storage_key=f"{s.clinic_id}/{uuid.uuid4().hex}",
            created_by_user_id=s.dentist.id,
        )
        session.add(adjunto)
        await session.commit()

    async def _dar_de_baja() -> int:
        async with AsyncSession(committed_engine, expire_on_commit=False) as session:
            try:
                await AttachmentService(session, principal, storage, MAX).remove(
                    ficha.record_id, adjunto.id, RemovalCreate(reason="Baja concurrente ficticia")
                )
            except DomainError as exc:
                assert exc.detail == "attachment_already_removed"
                return exc.status_code
            return 201

    resultados = await asyncio.gather(_dar_de_baja(), _dar_de_baja())

    assert sorted(resultados) == [201, 409]
    async with AsyncSession(committed_engine) as session:
        assert (
            await session.scalar(select(func.count()).select_from(ClinicalAttachmentRemoval)) == 1
        )
