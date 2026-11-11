"""Contrato de `AttachmentStorage` (C-15, D7, spec `clinical/attachments`).

La misma batería corre contra la implementación de disco (directorio temporal) y contra un doble
en memoria de pruebas: guardar, abrir, ausencia, no sobrescritura y clave que escapa de la raíz.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from app.modules.clinical.storage.base import (
    AttachmentStorage,
    InvalidStorageKey,
    StorageKeyExists,
    StorageObjectMissing,
)
from app.modules.clinical.storage.local import LocalAttachmentStorage

from tests.clinical_storage import MemoryAttachmentStorage

CLAVE = "11111111-2222-3333-4444-555555555555/0123456789abcdef0123456789abcdef"


async def _chunks(*partes: bytes) -> AsyncIterator[bytes]:
    for parte in partes:
        yield parte


async def _leer(storage: AttachmentStorage, key: str) -> bytes:
    return b"".join([parte async for parte in storage.open(key)])


@pytest.fixture(params=["local", "memoria"])
def storage(request: pytest.FixtureRequest, tmp_path: Path) -> AttachmentStorage:
    if request.param == "local":
        return LocalAttachmentStorage(tmp_path / "raiz")
    return MemoryAttachmentStorage()


async def test_guardar_y_abrir(storage: AttachmentStorage) -> None:
    escritos = await storage.put(CLAVE, _chunks(b"\x89PNG", b"datos-sinteticos"))

    assert escritos == len(b"\x89PNGdatos-sinteticos")
    assert await storage.exists(CLAVE)
    assert await _leer(storage, CLAVE) == b"\x89PNGdatos-sinteticos"


async def test_ausencia(storage: AttachmentStorage) -> None:
    assert not await storage.exists(CLAVE)
    with pytest.raises(StorageObjectMissing):
        await _leer(storage, CLAVE)


async def test_no_sobrescribe(storage: AttachmentStorage) -> None:
    await storage.put(CLAVE, _chunks(b"original"))

    with pytest.raises(StorageKeyExists):
        await storage.put(CLAVE, _chunks(b"pisado"))

    assert await _leer(storage, CLAVE) == b"original"


async def test_descartar_un_huerfano(storage: AttachmentStorage) -> None:
    await storage.put(CLAVE, _chunks(b"huerfano"))

    await storage.discard(CLAVE)

    assert not await storage.exists(CLAVE)


@pytest.mark.parametrize(
    "clave", ["../x", "a/../../x", "/etc/passwd", "a\\..\\..\\x", "", "a/./b", "C:/x"]
)
async def test_clave_que_escapa_de_la_raiz(storage: AttachmentStorage, clave: str) -> None:
    with pytest.raises(InvalidStorageKey):
        await storage.put(clave, _chunks(b"x"))
    with pytest.raises(InvalidStorageKey):
        await storage.exists(clave)


async def test_el_disco_no_escribe_fuera_de_la_raiz(tmp_path: Path) -> None:
    raiz = tmp_path / "raiz"
    storage = LocalAttachmentStorage(raiz)

    with pytest.raises(InvalidStorageKey):
        await storage.put("../fuera.bin", _chunks(b"x"))

    assert not (tmp_path / "fuera.bin").exists()
