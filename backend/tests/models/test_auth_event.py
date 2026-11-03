"""`auth_event`: append-only por trigger, tenant obligatorio y payload acotado (C-03)."""

import uuid
from typing import Any

import pytest
from app.models import AuthEvent, AuthEventType
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_clinic, make_user

pytestmark = pytest.mark.integration

_SIN_VALOR = object()


async def _evento(db_session: AsyncSession, **overrides: Any) -> AuthEvent:
    clinic = overrides.pop("clinic", None) or await make_clinic(db_session)
    user = overrides.pop("user", _SIN_VALOR)
    if user is _SIN_VALOR:
        user = await make_user(db_session, clinic)
    values: dict[str, Any] = {
        "clinic_id": clinic.id,
        "user_id": user.id if user is not None else None,
        "event": AuthEventType.LOGIN_SUCCESS,
        "payload": {"reason": "ok"},
    }
    values.update(overrides)
    evento = AuthEvent(**values)
    db_session.add(evento)
    await db_session.flush()
    return evento


async def test_update_es_rechazado_y_la_fila_queda_intacta(db_session: AsyncSession) -> None:
    """WHEN se intenta UPDATE sobre auth_event THEN la base lo rechaza y no cambia nada."""
    evento = await _evento(db_session)

    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE auth_event SET event = 'logout' WHERE id = :id"), {"id": evento.id}
            )

    actual = await db_session.scalar(select(AuthEvent.event).where(AuthEvent.id == evento.id))
    assert actual is AuthEventType.LOGIN_SUCCESS


async def test_delete_es_rechazado_y_la_fila_sigue_existiendo(db_session: AsyncSession) -> None:
    """WHEN se intenta DELETE sobre auth_event THEN la base lo rechaza."""
    evento = await _evento(db_session)

    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("DELETE FROM auth_event WHERE id = :id"), {"id": evento.id}
            )

    assert (
        await db_session.scalar(select(AuthEvent.id).where(AuthEvent.id == evento.id)) == evento.id
    )


async def test_clinic_id_es_obligatorio(db_session: AsyncSession) -> None:
    """WHEN un evento no declara clínica THEN NOT NULL lo rechaza."""
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(AuthEvent(event=AuthEventType.LOGIN_FAILED, payload={}))
            await db_session.flush()


async def test_user_de_otra_clinica_es_rechazado_por_la_fk_compuesta(
    db_session: AsyncSession,
) -> None:
    """WHEN el evento apunta a un usuario de otra clínica THEN la FK compuesta lo rechaza."""
    clinic_a = await make_clinic(db_session)
    clinic_b = await make_clinic(db_session)
    user_b = await make_user(db_session, clinic_b)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                AuthEvent(
                    clinic_id=clinic_a.id,
                    user_id=user_b.id,
                    event=AuthEventType.LOGIN_SUCCESS,
                    payload={},
                )
            )
            await db_session.flush()


@pytest.mark.parametrize("payload", ['"texto"', "42", "true", "null"])
async def test_payload_debe_ser_objeto_o_array(db_session: AsyncSession, payload: str) -> None:
    """WHEN payload no es objeto ni array THEN el CHECK lo rechaza."""
    evento = await _evento(db_session)

    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "INSERT INTO auth_event (clinic_id, event, payload) "
                    "VALUES (:cid, 'login_failed', CAST(:payload AS jsonb))"
                ),
                {"cid": evento.clinic_id, "payload": payload},
            )


async def test_evento_sin_usuario_usa_huella_de_sujeto(db_session: AsyncSession) -> None:
    """WHEN el sujeto es desconocido THEN se guarda `user_id NULL` + `subject_hash`."""
    clinic = await make_clinic(db_session)
    huella = "a" * 64

    evento = await _evento(
        db_session,
        clinic=clinic,
        user=None,
        event=AuthEventType.LOGIN_FAILED,
        subject_hash=huella,
        payload={"reason": "unknown_subject"},
    )

    assert evento.user_id is None
    assert evento.subject_hash == huella
    assert uuid.UUID(str(evento.clinic_id)) == clinic.id
