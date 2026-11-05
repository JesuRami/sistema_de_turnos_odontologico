"""Catálogo cerrado de motivos de cancelación del paciente (C-08, D7, decisión abierta #3).

Es la única fuente de verdad: lo usa el schema del `PATCH` y lo expone la vista. La causa
que se guarda en `appointment.cancellation_reason` es siempre `paciente`; este motivo fino
viaja en el evento como `patient_reason`, así el reporte por causa de C-13 no cambia.
"""

from __future__ import annotations

import enum

from pydantic import BaseModel


class PatientReason(enum.StrEnum):
    NO_PUEDO_ASISTIR = "no_puedo_asistir"
    ENFERMEDAD = "enfermedad"
    VIAJE = "viaje"
    PROBLEMA_ECONOMICO = "problema_economico"
    OTRO = "otro"


class ReasonOption(BaseModel):
    value: PatientReason
    label: str


_LABELS = {
    PatientReason.NO_PUEDO_ASISTIR: "No puedo asistir",
    PatientReason.ENFERMEDAD: "Enfermedad",
    PatientReason.VIAJE: "Viaje",
    PatientReason.PROBLEMA_ECONOMICO: "Problema económico",
    PatientReason.OTRO: "Otro",
}

# En el orden del enum, que es el orden en que la UI los muestra.
REASON_OPTIONS = tuple(ReasonOption(value=r, label=_LABELS[r]) for r in PatientReason)
