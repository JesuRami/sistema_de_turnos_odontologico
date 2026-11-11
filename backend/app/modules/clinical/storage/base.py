"""Interfaz de almacenamiento de adjuntos clínicos (C-15, D7).

Cambiar de implementación (disco hoy, S3-compatible después) no toca tablas ni API. Contrato:

- `put(key, chunks)` escribe en modo exclusivo (nunca sobrescribe: `StorageKeyExists`) y
  devuelve los bytes escritos.
- `open(key)` itera el contenido; ausente → `StorageObjectMissing`.
- `exists(key)`.
- `discard(key)`: **solo** para quitar un huérfano que nunca fue visible (la fila de metadatos
  no llegó a confirmarse). Ninguna operación de negocio borra un objeto.

Las claves las genera el servidor (`<clinic_id>/<uuid hex>`); toda implementación rechaza una
clave que no tenga esa forma segura (`InvalidStorageKey`) antes de tocar el medio.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Protocol

_KEY_RE = re.compile(r"^[0-9A-Za-z_-]{1,64}(/[0-9A-Za-z_-]{1,64}){0,3}$")


class StorageError(RuntimeError):
    """Falla del almacenamiento (mensaje sin rutas ni datos del paciente)."""


class InvalidStorageKey(StorageError):
    pass


class StorageKeyExists(StorageError):
    pass


class StorageObjectMissing(StorageError):
    pass


def validate_key(key: str) -> str:
    """Solo segmentos alfanuméricos separados por `/`: sin `..`, raíz, unidad ni `\\`."""
    if not _KEY_RE.match(key):
        raise InvalidStorageKey("clave de almacenamiento inválida")
    return key


class AttachmentStorage(Protocol):
    async def put(self, key: str, chunks: AsyncIterator[bytes]) -> int: ...

    def open(self, key: str) -> AsyncIterator[bytes]: ...

    async def exists(self, key: str) -> bool: ...

    async def discard(self, key: str) -> None: ...
