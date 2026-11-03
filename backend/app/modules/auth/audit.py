"""Auditoría de seguridad de C-03 (tabla append-only `auth_event`).

Reglas (design §15):

- Mutaciones administrativas y cambio de contraseña: `record_event` en la
  **misma transacción** que la mutación (si falla, no persiste nada).
- Intentos de login/refresh/logout: `record_best_effort` en un savepoint; un
  fallo de auditoría nunca cambia la respuesta ni filtra si el usuario existía.
- Sin PII ni credenciales: sujeto por `user_id` o huella `sha256(email)`;
  `payload` solo con códigos internos.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuthEvent, AuthEventType

logger = logging.getLogger("app.auth.audit")

Payload = dict[str, Any] | list[Any]


def subject_hash(email: str) -> str:
    """Huella estable del email normalizado (pseudonimización, no anonimato)."""
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def _build(
    *,
    clinic_id: uuid.UUID,
    event: AuthEventType,
    user_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    subject_hash: str | None,
    payload: Payload | None,
) -> AuthEvent:
    return AuthEvent(
        clinic_id=clinic_id,
        event=event,
        user_id=user_id,
        actor_user_id=actor_user_id,
        subject_hash=subject_hash,
        payload=payload if payload is not None else {},
    )


async def record_event(
    session: AsyncSession,
    *,
    clinic_id: uuid.UUID,
    event: AuthEventType,
    user_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    subject_hash: str | None = None,
    payload: Payload | None = None,
) -> AuthEvent:
    """Escribe el evento en la transacción del llamador (sin commit propio)."""
    evento = _build(
        clinic_id=clinic_id,
        event=event,
        user_id=user_id,
        actor_user_id=actor_user_id,
        subject_hash=subject_hash,
        payload=payload,
    )
    session.add(evento)
    await session.flush()
    return evento


async def record_best_effort(
    session: AsyncSession,
    *,
    clinic_id: uuid.UUID,
    event: AuthEventType,
    user_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    subject_hash: str | None = None,
    payload: Payload | None = None,
) -> bool:
    """Intenta auditar sin condicionar la respuesta de autenticación."""
    evento = _build(
        clinic_id=clinic_id,
        event=event,
        user_id=user_id,
        actor_user_id=actor_user_id,
        subject_hash=subject_hash,
        payload=payload,
    )
    try:
        async with session.begin_nested():
            session.add(evento)
            await session.flush()
    except SQLAlchemyError:
        logger.warning("auth_event no persistido: event=%s clinic_id=%s", event.value, clinic_id)
        return False
    return True
