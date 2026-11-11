"""Almacenamiento de adjuntos en disco (volumen Docker `clinical_files`, C-15, D7).

La ruta final se normaliza y se verifica dentro de la raíz (defensa además de `validate_key`); la
escritura es exclusiva (`xb`) y la E/S de archivo corre en un thread para no bloquear el loop.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

from app.modules.clinical.storage.base import (
    InvalidStorageKey,
    StorageKeyExists,
    StorageObjectMissing,
    validate_key,
)

CHUNK_BYTES = 64 * 1024


class LocalAttachmentStorage:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        destino = (self.root / validate_key(key)).resolve()
        if not destino.is_relative_to(self.root):
            raise InvalidStorageKey("clave de almacenamiento inválida")
        return destino

    async def put(self, key: str, chunks: AsyncIterator[bytes]) -> int:
        destino = self._path(key)
        await asyncio.to_thread(destino.parent.mkdir, parents=True, exist_ok=True)
        try:
            archivo = await asyncio.to_thread(open, destino, "xb")
        except FileExistsError:
            raise StorageKeyExists("la clave ya existe") from None
        total = 0
        try:
            async for parte in chunks:
                await asyncio.to_thread(archivo.write, parte)
                total += len(parte)
            await asyncio.to_thread(archivo.flush)
            await asyncio.to_thread(os.fsync, archivo.fileno())
        except BaseException:
            await asyncio.to_thread(archivo.close)
            await asyncio.to_thread(destino.unlink, missing_ok=True)
            raise
        await asyncio.to_thread(archivo.close)
        return total

    async def open(self, key: str) -> AsyncIterator[bytes]:
        origen = self._path(key)
        try:
            archivo = await asyncio.to_thread(open, origen, "rb")
        except FileNotFoundError:
            raise StorageObjectMissing("objeto ausente") from None
        try:
            while parte := await asyncio.to_thread(archivo.read, CHUNK_BYTES):
                yield parte
        finally:
            await asyncio.to_thread(archivo.close)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).is_file)

    async def discard(self, key: str) -> None:
        await asyncio.to_thread(self._path(key).unlink, missing_ok=True)
