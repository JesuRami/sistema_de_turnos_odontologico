"""Búsqueda y alta rápida de pacientes (C-05, US-011 CA-1, design D11).

- Búsqueda: si el término es un teléfono válido, match exacto por E.164
  (reutiliza `find_patients_by_phone` de C-02); si no, similitud trigram sobre
  `full_name` con el operador `%` (usa el GIN `ix_patient_full_name_trgm`).
- Alta: duplicado = mismo `phone_e164` y mismo `lower(btrim(full_name))` en la
  clínica (sin `unaccent`, no instalada). Mismo teléfono con otro nombre se
  acepta (familias, SU-03).
- Ningún error lleva nombre, teléfono ni email (regla 13).
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import DomainError
from app.common.phone import InvalidPhoneError, normalize_phone_e164
from app.common.principal import Principal
from app.models import Patient
from app.modules.clinic.service import create_patient, find_patients_by_phone
from app.modules.patients.schemas import (
    PatientCreate,
    PatientRead,
    PatientSearchResult,
)

QUERY_MIN = 3
QUERY_MAX = 100
SEARCH_LIMIT = 20
PHONE_MAX = 32
EMAIL_MAX = 254
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Un término "parece teléfono" si solo tiene dígitos y separadores habituales.
_PHONE_LIKE_RE = re.compile(r"^[+\d][\d\s().-]*$")


class PatientsService:
    """Casos de uso de pacientes de la clínica del principal."""

    def __init__(self, session: AsyncSession, principal: Principal) -> None:
        self.session = session
        self.principal = principal

    async def search(self, raw: str) -> PatientSearchResult:
        termino = raw.strip()
        if len(termino) < QUERY_MIN:
            raise DomainError(422, "query_too_short")
        if len(termino) > QUERY_MAX:
            raise DomainError(422, "query_too_long")
        encontrados: Sequence[Patient] | None = None
        if _PHONE_LIKE_RE.match(termino):
            try:
                encontrados = await find_patients_by_phone(
                    self.session, self.principal.clinic_id, termino
                )
            except InvalidPhoneError:
                encontrados = None
        if encontrados is None:
            encontrados = await self._by_name(termino)
        return PatientSearchResult(
            items=[PatientRead.model_validate(p) for p in encontrados[:SEARCH_LIMIT]]
        )

    async def _by_name(self, termino: str) -> Sequence[Patient]:
        similitud = func.similarity(Patient.full_name, termino)
        stmt = (
            select(Patient)
            .where(
                Patient.clinic_id == self.principal.clinic_id,
                Patient.archived_at.is_(None),
                Patient.full_name.op("%")(termino),
            )
            .order_by(similitud.desc(), Patient.id)
            .limit(SEARCH_LIMIT)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def create(self, payload: PatientCreate) -> PatientRead:
        phone = (payload.phone or "").strip() or None
        email = (payload.email or "").strip().lower() or None
        if phone is None and email is None:
            raise DomainError(422, "contact_required")
        phone_e164: str | None = None
        if phone is not None:
            try:
                if len(phone) > PHONE_MAX:
                    raise InvalidPhoneError
                phone_e164 = normalize_phone_e164(phone)
            except InvalidPhoneError:
                raise DomainError(422, "invalid_phone") from None
        if email is not None and (len(email) > EMAIL_MAX or not _EMAIL_RE.match(email)):
            raise DomainError(422, "invalid_email")
        if phone_e164 is not None:
            await self._assert_not_duplicate(phone_e164, payload.full_name)

        patient = await create_patient(
            self.session,
            self.principal.clinic_id,
            full_name=payload.full_name,
            phone=phone_e164,
            email=email,
            dni=payload.dni,
            whatsapp_opt_in=payload.whatsapp_opt_in,
        )
        await self.session.commit()
        await self.session.refresh(patient)
        return PatientRead.model_validate(patient)

    async def _assert_not_duplicate(self, phone_e164: str, full_name: str) -> None:
        existente = await self.session.scalar(
            select(Patient.id)
            .where(
                Patient.clinic_id == self.principal.clinic_id,
                Patient.archived_at.is_(None),
                Patient.phone_e164 == phone_e164,
                func.lower(func.btrim(Patient.full_name)) == full_name.strip().lower(),
            )
            .order_by(Patient.created_at, Patient.id)
            .limit(1)
        )
        if existente is not None:
            raise DomainError(409, "patient_duplicate", extra={"patient_id": str(existente)})
