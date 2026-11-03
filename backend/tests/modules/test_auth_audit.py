"""Auditoría de seguridad: transaccional, sin PII y best-effort en intentos."""

import logging

import pytest
from app.models import AuthEvent, AuthEventType, User
from app.modules.auth.audit import record_best_effort, record_event, subject_hash
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_clinic, make_user

pytestmark = pytest.mark.integration

CLAVE = "clave-de-prueba-no-real-123"


async def _contar(session: AsyncSession, modelo: type[object]) -> int:
    return int(await session.scalar(select(func.count()).select_from(modelo)) or 0)


async def test_evento_y_mutacion_persisten_juntos_y_revierten_juntos(
    db_session: AsyncSession,
) -> None:
    """WHEN el alta y su evento comparten transacción THEN ambos persisten o ninguno."""
    clinic = await make_clinic(db_session)

    savepoint = await db_session.begin_nested()
    user = await make_user(db_session, clinic)
    await record_event(
        db_session,
        clinic_id=clinic.id,
        event=AuthEventType.USER_CREATED,
        user_id=user.id,
        actor_user_id=user.id,
        payload={"role": "admin"},
    )
    assert await _contar(db_session, AuthEvent) >= 1
    await savepoint.rollback()

    assert await _contar(db_session, AuthEvent) == 0
    assert await _contar(db_session, User) == 0


async def test_evento_de_login_fallido_sin_usuario_guarda_solo_huella(
    db_session: AsyncSession,
) -> None:
    """WHEN el email no existe THEN `user_id NULL` + huella y ningún texto con el email."""
    clinic = await make_clinic(db_session)
    email = "desconocido@example.com"

    evento = await record_event(
        db_session,
        clinic_id=clinic.id,
        event=AuthEventType.LOGIN_FAILED,
        subject_hash=subject_hash(email),
        payload={"reason": "bad_password"},
    )

    assert evento.user_id is None
    assert evento.subject_hash == subject_hash(email)
    texto = f"{evento.payload} {evento.subject_hash}"
    assert email not in texto
    assert "../example.com" not in texto


async def test_ningun_campo_guarda_email_telefono_clave_ni_tokens(
    db_session: AsyncSession,
) -> None:
    """WHEN se audita cualquier evento THEN no hay PII ni credenciales en la fila."""
    clinic = await make_clinic(db_session)
    user = await make_user(db_session, clinic)

    evento = await record_event(
        db_session,
        clinic_id=clinic.id,
        event=AuthEventType.LOGIN_SUCCESS,
        user_id=user.id,
        payload={"reason": "ok"},
    )
    await db_session.flush()

    valores = [str(getattr(evento, columna.name)) for columna in AuthEvent.__table__.columns]
    texto = " ".join(valores)
    for prohibido in (user.email, CLAVE, user.password_hash, "Bearer", "refresh_token"):
        assert prohibido not in texto


async def test_best_effort_no_propaga_fallo_y_avisa_sin_credenciales(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """WHEN la auditoría de un intento falla THEN la respuesta sigue y queda warning sin PII."""
    clinic_a = await make_clinic(db_session)
    clinic_b = await make_clinic(db_session)
    user_b = await make_user(db_session, clinic_b)

    with caplog.at_level(logging.WARNING):
        ok = await record_best_effort(
            db_session,
            clinic_id=clinic_a.id,
            event=AuthEventType.LOGIN_SUCCESS,
            user_id=user_b.id,
            payload={"reason": "ok"},
        )

    assert ok is False
    assert "auth_event" in caplog.text
    assert CLAVE not in caplog.text
    assert user_b.email not in caplog.text
    assert await _contar(db_session, AuthEvent) == 0


async def test_best_effort_escribe_cuando_la_db_acepta(db_session: AsyncSession) -> None:
    """WHEN el insert es válido THEN best-effort persiste y devuelve True."""
    clinic = await make_clinic(db_session)

    ok = await record_best_effort(
        db_session,
        clinic_id=clinic.id,
        event=AuthEventType.LOGOUT,
        payload={"reason": "user_logout"},
    )

    assert ok is True
    assert await _contar(db_session, AuthEvent) == 1
