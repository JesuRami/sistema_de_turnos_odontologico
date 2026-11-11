"""Adjuntos clínicos (C-15, D7, spec `clinical/attachments`).

Subida: tope de lectura por partes (no `Content-Length`), tipo por *magic bytes*, `sha256`,
`storage_key` opaco del servidor y fila + auditoría en la misma transacción. Si la transacción
falla tras escribir el archivo, se intenta quitar el huérfano (nunca fue visible); si eso falla,
se loguea solo el `storage_key`. Baja lógica sin borrar el archivo. Descarga solo por la API.
"""

from __future__ import annotations

import hashlib
import logging
import unicodedata
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, cast

from fastapi import Request, UploadFile
from sqlalchemy import exists, func, select
from sqlalchemy.engine import Row
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import DomainError
from app.common.principal import Principal
from app.core.settings import Settings
from app.models import (
    AttachmentKind,
    ClinicalAction,
    ClinicalAttachment,
    ClinicalAttachmentRemoval,
    ClinicalEvolution,
)
from app.models.clinical_attachment import DISPLAY_NAME_MAX_LENGTH
from app.modules.clinical.access import is_admin, resolve_record
from app.modules.clinical.audit import record_access
from app.modules.clinical.cursor import paginate_desc
from app.modules.clinical.schemas import (
    AttachmentRead,
    AttachmentsPage,
    RemovalCreate,
    RemovalRead,
)
from app.modules.clinical.storage.base import AttachmentStorage
from app.modules.clinical.storage.local import LocalAttachmentStorage

logger = logging.getLogger("app.clinical.attachments")

MAX_ACTIVE_PER_RECORD = 200
CHUNK = 64 * 1024
_MAGIC = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"%PDF-", "application/pdf"),
)


def get_attachment_storage(request: Request) -> AttachmentStorage:
    """Almacenamiento de la app (disco en `CLINICAL_STORAGE_ROOT`); los tests lo sustituyen."""
    actual = getattr(request.app.state, "clinical_storage", None)
    if actual is None:
        settings = cast(Settings, request.app.state.settings)
        actual = LocalAttachmentStorage(settings.CLINICAL_STORAGE_ROOT)
        request.app.state.clinical_storage = actual
    return cast(AttachmentStorage, actual)


def sniff_content_type(head: bytes) -> str | None:
    for firma, tipo in _MAGIC:
        if head.startswith(firma):
            return tipo
    return None


def sanitize_display_name(nombre: str | None) -> str:
    """Solo para mostrar: sin ruta, sin caracteres de control, acotado."""
    base = (nombre or "").replace("\\", "/").rsplit("/", 1)[-1]
    limpio = "".join(c for c in base if not unicodedata.category(c).startswith("C")).strip()
    return limpio[:DISPLAY_NAME_MAX_LENGTH] or "archivo"


async def _iter_upload(upload: UploadFile) -> AsyncIterator[bytes]:
    await upload.seek(0)
    while parte := await upload.read(CHUNK):
        yield parte


@dataclass(frozen=True, slots=True)
class Download:
    content_type: str
    display_name: str
    chunks: AsyncIterator[bytes]


_COLUMNS = (
    ClinicalAttachment.id,
    ClinicalAttachment.kind,
    ClinicalAttachment.content_type,
    ClinicalAttachment.size_bytes,
    ClinicalAttachment.sha256,
    ClinicalAttachment.display_name,
    ClinicalAttachment.evolution_id,
    ClinicalAttachment.created_by_user_id,
    ClinicalAttachment.created_at,
)


def _read(fila: Row[Any]) -> AttachmentRead:
    return AttachmentRead(
        id=fila.id,
        kind=fila.kind,
        content_type=fila.content_type,
        size_bytes=fila.size_bytes,
        sha256=fila.sha256,
        display_name=fila.display_name,
        evolution_id=fila.evolution_id,
        created_by_user_id=fila.created_by_user_id,
        created_at=fila.created_at,
        removed=fila.removal_reason is not None,
        removal_reason=fila.removal_reason,
        removed_at=fila.removed_at,
    )


class AttachmentService:
    def __init__(
        self,
        session: AsyncSession,
        principal: Principal,
        storage: AttachmentStorage,
        max_bytes: int,
    ) -> None:
        self.session = session
        self.principal = principal
        self.storage = storage
        self.max_bytes = max_bytes

    async def upload(
        self,
        record_id: uuid.UUID,
        upload: UploadFile,
        kind: AttachmentKind,
        evolution_id: uuid.UUID | None,
    ) -> AttachmentRead:
        ficha = await resolve_record(self.session, self.principal, record_id, write=True)
        if evolution_id is not None:
            propia = await self.session.scalar(
                select(ClinicalEvolution.id).where(
                    ClinicalEvolution.id == evolution_id,
                    ClinicalEvolution.clinic_id == ficha.clinic_id,
                    ClinicalEvolution.record_id == ficha.id,
                )
            )
            if propia is None:
                raise DomainError(422, "evolution_not_found")
        activos = await self.session.scalar(
            select(func.count(ClinicalAttachment.id)).where(
                ClinicalAttachment.clinic_id == ficha.clinic_id,
                ClinicalAttachment.record_id == ficha.id,
                ~exists().where(ClinicalAttachmentRemoval.attachment_id == ClinicalAttachment.id),
            )
        )
        if (activos or 0) >= MAX_ACTIVE_PER_RECORD:
            raise DomainError(409, "attachment_limit_reached")

        digest = hashlib.sha256()
        total = 0
        cabecera = b""
        await upload.seek(0)
        while parte := await upload.read(CHUNK):
            total += len(parte)
            if total > self.max_bytes:
                raise DomainError(413, "attachment_too_large")
            if len(cabecera) < 8:
                cabecera += parte[: 8 - len(cabecera)]
            digest.update(parte)
        if total == 0:
            raise DomainError(422, "attachment_empty")
        tipo = sniff_content_type(cabecera)
        if tipo is None:
            raise DomainError(415, "unsupported_media_type")

        clave = f"{ficha.clinic_id}/{uuid.uuid4().hex}"
        await self.storage.put(clave, _iter_upload(upload))
        try:
            adjunto = ClinicalAttachment(
                clinic_id=ficha.clinic_id,
                record_id=ficha.id,
                evolution_id=evolution_id,
                kind=kind,
                content_type=tipo,
                size_bytes=total,
                sha256=digest.hexdigest(),
                display_name=sanitize_display_name(upload.filename),
                storage_key=clave,
                created_by_user_id=self.principal.user_id,
            )
            self.session.add(adjunto)
            await self.session.flush()
            await record_access(
                self.session,
                self.principal,
                ficha.id,
                ClinicalAction.ATTACHMENT_UPLOAD,
                object_type="clinical_attachment",
                object_id=adjunto.id,
                payload={"size_bytes": total},
            )
            await self.session.commit()
        except BaseException:
            try:
                await self.storage.discard(clave)
            except Exception:
                logger.error("attachment_orphan_cleanup_failed storage_key=%s", clave)
            raise
        return AttachmentRead(
            id=adjunto.id,
            kind=adjunto.kind,
            content_type=tipo,
            size_bytes=total,
            sha256=adjunto.sha256,
            display_name=adjunto.display_name,
            evolution_id=evolution_id,
            created_by_user_id=self.principal.user_id,
            created_at=adjunto.created_at,
        )

    def _select(self) -> Any:
        return select(
            *_COLUMNS,
            ClinicalAttachment.storage_key,
            ClinicalAttachmentRemoval.reason.label("removal_reason"),
            ClinicalAttachmentRemoval.created_at.label("removed_at"),
        ).outerjoin(
            ClinicalAttachmentRemoval,
            ClinicalAttachmentRemoval.attachment_id == ClinicalAttachment.id,
        )

    async def list(
        self, record_id: uuid.UUID, include_removed: bool, cursor: str | None, limit: int
    ) -> AttachmentsPage:
        if include_removed and not is_admin(self.principal):
            raise DomainError(403, "forbidden_role")
        ficha = await resolve_record(self.session, self.principal, record_id)
        stmt = self._select().where(
            ClinicalAttachment.clinic_id == ficha.clinic_id,
            ClinicalAttachment.record_id == ficha.id,
        )
        if not include_removed:
            stmt = stmt.where(ClinicalAttachmentRemoval.id.is_(None))
        filas, siguiente = await paginate_desc(
            self.session,
            stmt,
            ClinicalAttachment.created_at,
            ClinicalAttachment.id,
            cursor,
            limit,
        )
        await record_access(
            self.session,
            self.principal,
            ficha.id,
            ClinicalAction.ATTACHMENT_LIST,
            payload={"items": len(filas), "include_removed": include_removed},
        )
        await self.session.commit()
        return AttachmentsPage(items=[_read(f) for f in filas], next_cursor=siguiente)

    async def _get(self, ficha_clinic: uuid.UUID, ficha_id: uuid.UUID, aid: uuid.UUID) -> Any:
        fila = (
            await self.session.execute(
                self._select().where(
                    ClinicalAttachment.id == aid,
                    ClinicalAttachment.clinic_id == ficha_clinic,
                    ClinicalAttachment.record_id == ficha_id,
                )
            )
        ).one_or_none()
        if fila is None:
            raise DomainError(404, "attachment_not_found")
        return fila

    async def download(self, record_id: uuid.UUID, attachment_id: uuid.UUID) -> Download:
        ficha = await resolve_record(self.session, self.principal, record_id)
        fila = await self._get(ficha.clinic_id, ficha.id, attachment_id)
        if fila.removal_reason is not None and not is_admin(self.principal):
            raise DomainError(404, "attachment_not_found")
        if not await self.storage.exists(fila.storage_key):
            logger.error("attachment_object_missing attachment_id=%s", fila.id)
            raise RuntimeError("attachment_object_missing")
        await record_access(
            self.session,
            self.principal,
            ficha.id,
            ClinicalAction.ATTACHMENT_DOWNLOAD,
            object_type="clinical_attachment",
            object_id=fila.id,
        )
        await self.session.commit()
        return Download(
            content_type=fila.content_type,
            display_name=fila.display_name,
            chunks=self.storage.open(fila.storage_key),
        )

    async def remove(
        self, record_id: uuid.UUID, attachment_id: uuid.UUID, payload: RemovalCreate
    ) -> RemovalRead:
        ficha = await resolve_record(self.session, self.principal, record_id, write=True)
        fila = await self._get(ficha.clinic_id, ficha.id, attachment_id)
        if fila.removal_reason is not None:
            raise DomainError(409, "attachment_already_removed")
        baja = ClinicalAttachmentRemoval(
            clinic_id=ficha.clinic_id,
            attachment_id=fila.id,
            reason=payload.reason,
            removed_by_user_id=self.principal.user_id,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(baja)
                await self.session.flush()
        except IntegrityError:
            raise DomainError(409, "attachment_already_removed") from None
        await record_access(
            self.session,
            self.principal,
            ficha.id,
            ClinicalAction.ATTACHMENT_REMOVE,
            object_type="clinical_attachment",
            object_id=fila.id,
        )
        await self.session.commit()
        return RemovalRead(
            attachment_id=fila.id,
            reason=baja.reason,
            removed_by_user_id=baja.removed_by_user_id,
            removed_at=baja.created_at,
        )
