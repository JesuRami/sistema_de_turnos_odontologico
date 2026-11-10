"""Exportación de los datos de un paciente (C-14, D10): acceso y portabilidad mínimos.

Resguardo v1 de la pregunta Alta de `10` (Ley 25.326 art. 14 / Ley 26.529; validar con el asesor
legal): un admin entrega al paciente que lo pida **sus** datos operativos en un JSON legible.

Mismas columnas explícitas que la exportación completa de C-13 (regla 8) y filtro por la clínica
del principal en cada tabla (regla 4). Queda en `auth_event` (`data_exported`, `scope=patient`) sin
datos personales en el payload, solo ids y conteos.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.csv_export import to_json_value
from app.common.exceptions import DomainError
from app.models import (
    Appointment,
    AppointmentEvent,
    AuthEventType,
    Consent,
    Patient,
    WaitingListEntry,
    WaitlistOffer,
)
from app.modules.auth.audit import record_event
from app.modules.reports.exports import TABLES, ExportTable

FORMAT_VERSION = "patient-export/v1"
_CONSENT_COLUMNS = ("id", "channel", "status", "source", "changed_by_user_id", "changed_at")


def _columns(name: str) -> tuple[str, ...]:
    tabla: ExportTable = next(t for t in TABLES if t.name == name)
    return tabla.columns


def _rows(columns: Sequence[str], filas: Sequence[Any]) -> list[dict[str, Any]]:
    return [{c: to_json_value(v) for c, v in zip(columns, fila, strict=True)} for fila in filas]


class PatientExportService:
    def __init__(self, session: AsyncSession, clinic_id: uuid.UUID, user_id: uuid.UUID) -> None:
        self.session = session
        self.clinic_id = clinic_id
        self.user_id = user_id

    async def _select(
        self, model: Any, columns: Sequence[str], *where: Any
    ) -> list[dict[str, Any]]:
        stmt = (
            select(*[getattr(model, c) for c in columns])
            .where(model.clinic_id == self.clinic_id, *where)
            .order_by(model.id)
        )
        return _rows(columns, (await self.session.execute(stmt)).all())

    async def build(self, patient_id: uuid.UUID) -> dict[str, Any]:
        pacientes = await self._select(Patient, _columns("patients"), Patient.id == patient_id)
        if not pacientes:
            raise DomainError(404, "not_found")
        turnos = await self._select(
            Appointment, _columns("appointments"), Appointment.patient_id == patient_id
        )
        ids_turnos = [uuid.UUID(str(t["id"])) for t in turnos]
        eventos = (
            await self._select(
                AppointmentEvent,
                _columns("appointment_events"),
                AppointmentEvent.appointment_id.in_(ids_turnos),
            )
            if ids_turnos
            else []
        )
        entradas = await self._select(
            WaitingListEntry,
            _columns("waiting_list_entries"),
            WaitingListEntry.patient_id == patient_id,
        )
        ids_entradas = [uuid.UUID(str(e["id"])) for e in entradas]
        ofertas = (
            await self._select(
                WaitlistOffer, _columns("waitlist_offers"), WaitlistOffer.entry_id.in_(ids_entradas)
            )
            if ids_entradas
            else []
        )
        consentimientos = await self._select(
            Consent, _CONSENT_COLUMNS, Consent.patient_id == patient_id
        )
        return {
            "format": FORMAT_VERSION,
            "patient": pacientes[0],
            "consents": consentimientos,
            "appointments": turnos,
            "appointment_events": eventos,
            "waiting_list_entries": entradas,
            "waitlist_offers": ofertas,
        }

    async def audit(self, patient_id: uuid.UUID, documento: dict[str, Any]) -> None:
        conteos = {
            clave: len(valor) for clave, valor in documento.items() if isinstance(valor, list)
        }
        await record_event(
            self.session,
            clinic_id=self.clinic_id,
            event=AuthEventType.DATA_EXPORTED,
            user_id=self.user_id,
            actor_user_id=self.user_id,
            payload={
                "scope": "patient",
                "patient_id": str(patient_id),
                "format": "json",
                "counts": conteos,
            },
        )
        await self.session.commit()
