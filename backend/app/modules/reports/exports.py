"""Exportación completa de datos de la clínica (C-13, US-051 CA-3, sin lock-in).

ZIP con turnos, pacientes operativos y eventos de auditoría. Cada tabla se lee
por lotes con cursor por `id` (regla 8) y se escribe a un archivo temporal que
se desborda a disco, así que la memoria no crece con el volumen. Todo se filtra
por `clinic_id` del principal (regla 4). La ejecución queda en `auth_event`.
"""

from __future__ import annotations

import json
import tempfile
import uuid
import zipfile
from collections.abc import AsyncIterator, Iterator, Sequence
from dataclasses import dataclass
from typing import IO, Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.csv_export import BOM, csv_text, to_json_value
from app.models import Appointment, AppointmentEvent, AuthEventType, Patient
from app.modules.auth.audit import record_event

BATCH = 1000
SPOOL_BYTES = 8 * 1024 * 1024
ExportFormat = Literal["csv", "json"]


@dataclass(frozen=True, slots=True)
class ExportTable:
    name: str
    model: Any
    columns: tuple[str, ...]


# Columnas explícitas (nada de SELECT *). `id` va primero: es la clave del cursor.
TABLES: tuple[ExportTable, ...] = (
    ExportTable(
        "appointments",
        Appointment,
        (
            "id",
            "patient_id",
            "professional_id",
            "chair_id",
            "starts_at",
            "ends_at",
            "status",
            "origin",
            "is_overbooking",
            "overbooking_reason",
            "cancellation_reason",
            "cancellation_note",
            "cancelled_at",
            "notes",
            "created_by_user_id",
        ),
    ),
    ExportTable(
        "patients",
        Patient,
        (
            "id",
            "full_name",
            "phone_e164",
            "email",
            "dni",
            "whatsapp_opt_in",
            "privacy_consent_at",
            "privacy_consent_version",
            "archived_at",
            "merged_into_patient_id",
        ),
    ),
    ExportTable(
        "appointment_events",
        AppointmentEvent,
        (
            "id",
            "appointment_id",
            "actor_type",
            "actor_user_id",
            "event",
            "from_status",
            "to_status",
            "payload",
            "slot_starts_at",
            "slot_ends_at",
            "professional_id",
            "chair_id",
            "created_at",
        ),
    ),
)


class ExportService:
    def __init__(self, session: AsyncSession, clinic_id: uuid.UUID, user_id: uuid.UUID) -> None:
        self.session = session
        self.clinic_id = clinic_id
        self.user_id = user_id

    async def _batches(self, table: ExportTable) -> AsyncIterator[Sequence[Any]]:
        model = table.model
        ultimo: uuid.UUID | None = None
        while True:
            stmt = (
                select(*[getattr(model, c) for c in table.columns])
                .where(model.clinic_id == self.clinic_id)
                .order_by(model.id)
                .limit(BATCH)
            )
            if ultimo is not None:
                stmt = stmt.where(model.id > ultimo)
            filas = (await self.session.execute(stmt)).all()
            if not filas:
                return
            yield filas
            if len(filas) < BATCH:
                return
            ultimo = filas[-1][0]

    async def _write_table(self, zf: zipfile.ZipFile, table: ExportTable, fmt: ExportFormat) -> int:
        total = 0
        with zf.open(f"{table.name}.{fmt}", "w", force_zip64=True) as destino:
            if fmt == "csv":
                destino.write(BOM.encode("utf-8"))
                destino.write(csv_text(table.columns, [], header=True).encode("utf-8"))
            else:
                destino.write(b"[")
            async for lote in self._batches(table):
                if fmt == "csv":
                    destino.write(csv_text(table.columns, lote, header=False).encode("utf-8"))
                else:
                    trozos = [
                        json.dumps(
                            {c: to_json_value(v) for c, v in zip(table.columns, fila, strict=True)},
                            ensure_ascii=False,
                        )
                        for fila in lote
                    ]
                    prefijo = b"," if total else b""
                    destino.write(prefijo + ",".join(trozos).encode("utf-8"))
                total += len(lote)
            if fmt == "json":
                destino.write(b"]")
        return total

    async def build(self, fmt: ExportFormat) -> tuple[IO[bytes], int, dict[str, int]]:
        """ZIP en un archivo temporal ya posicionado al inicio, su tamaño y los conteos."""
        archivo = tempfile.SpooledTemporaryFile(max_size=SPOOL_BYTES)
        conteos: dict[str, int] = {}
        try:
            with zipfile.ZipFile(archivo, "w", zipfile.ZIP_DEFLATED) as zf:
                for tabla in TABLES:
                    conteos[tabla.name] = await self._write_table(zf, tabla, fmt)
            tamano = archivo.tell()
            archivo.seek(0)
        except BaseException:
            archivo.close()
            raise
        return archivo, tamano, conteos

    async def audit(self, fmt: ExportFormat, conteos: dict[str, int]) -> None:
        """Registra la exportación (sin datos de pacientes) y confirma."""
        await record_event(
            self.session,
            clinic_id=self.clinic_id,
            event=AuthEventType.DATA_EXPORTED,
            user_id=self.user_id,
            actor_user_id=self.user_id,
            payload={"format": fmt, "counts": conteos},
        )
        await self.session.commit()


def iter_file(archivo: IO[bytes], chunk: int = 64 * 1024) -> Iterator[bytes]:
    """Lee el ZIP por trozos y cierra el temporal al terminar."""
    try:
        while True:
            trozo = archivo.read(chunk)
            if not trozo:
                break
            yield trozo
    finally:
        archivo.close()
