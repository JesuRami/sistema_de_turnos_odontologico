"""Dobles de almacenamiento de adjuntos para tests (C-15). No reemplazan la base (regla 9).

- `MemoryAttachmentStorage`: cumple el mismo contrato que el disco (se prueba con la batería de
  `test_storage_contract.py`).
- `FailingAttachmentStorage`: falla al escribir, para la ruta "Falla del almacenamiento".
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from app.modules.clinical.storage.base import (
    StorageError,
    StorageKeyExists,
    StorageObjectMissing,
    validate_key,
)


class MemoryAttachmentStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, chunks: AsyncIterator[bytes]) -> int:
        validate_key(key)
        if key in self.objects:
            raise StorageKeyExists("la clave ya existe")
        datos = b"".join([parte async for parte in chunks])
        self.objects[key] = datos
        return len(datos)

    async def open(self, key: str) -> AsyncIterator[bytes]:
        validate_key(key)
        if key not in self.objects:
            raise StorageObjectMissing("objeto ausente")
        yield self.objects[key]

    async def exists(self, key: str) -> bool:
        return validate_key(key) in self.objects

    async def discard(self, key: str) -> None:
        self.objects.pop(validate_key(key), None)


class FailingAttachmentStorage(MemoryAttachmentStorage):
    async def put(self, key: str, chunks: AsyncIterator[bytes]) -> int:
        validate_key(key)
        raise StorageError("disco no disponible")
