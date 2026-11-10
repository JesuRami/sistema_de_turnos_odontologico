"""Invariantes de base de la lista de espera (C-12, D1; reglas 4, 7, 9 y RN-LE-01).

Postgres real: la unicidad de entradas activas, los CHECKs de preferencias, las FKs compuestas, la
oferta pendiente única y el append-only de `waitlist_event` los impone la base. Datos ficticios.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import pytest
from app.models import (
    ActorType,
    WaitingListStatus,
    WaitlistEvent,
    WaitlistEventType,
    WaitlistOfferStatus,
)
from sqlalchemy import delete, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_appointment, make_patient, make_professional
from tests.waitlist_helpers import make_entry, make_offer, make_wait_scene

pytestmark = pytest.mark.integration

INICIO = datetime(2030, 1, 10, 13, 0, tzinfo=UTC)


async def _falla(session: AsyncSession, coro: object, match: str) -> None:
    with pytest.raises((IntegrityError, DBAPIError), match=match):
        async with session.begin_nested():
            await coro  # type: ignore[misc]


async def test_entrada_minima_se_guarda(db_session: AsyncSession) -> None:
    s = await make_wait_scene(db_session)
    entry = await make_entry(db_session, s.clinic, s.patient)

    assert entry.status is WaitingListStatus.WAITING
    assert entry.consecutive_expired == 0
    assert entry.prioritized_at is None


async def test_duplicado_activo_mismo_profesional_se_rechaza(db_session: AsyncSession) -> None:
    s = await make_wait_scene(db_session)
    await make_entry(db_session, s.clinic, s.patient, professional=s.professional)

    await _falla(
        db_session,
        make_entry(db_session, s.clinic, s.patient, professional=s.professional),
        "uq_waiting_list_entry_active",
    )


async def test_cualquiera_cuenta_como_un_valor(db_session: AsyncSession) -> None:
    s = await make_wait_scene(db_session)
    await make_entry(db_session, s.clinic, s.patient, status=WaitingListStatus.OFFERED)

    await _falla(
        db_session, make_entry(db_session, s.clinic, s.patient), "uq_waiting_list_entry_active"
    )


async def test_profesionales_distintos_son_colas_distintas(db_session: AsyncSession) -> None:
    s = await make_wait_scene(db_session)
    await make_entry(db_session, s.clinic, s.patient)
    otra = await make_entry(db_session, s.clinic, s.patient, professional=s.professional)

    assert otra.id is not None


@pytest.mark.parametrize(
    "estado",
    [WaitingListStatus.CONVERTED, WaitingListStatus.EXPIRED, WaitingListStatus.WITHDRAWN],
)
async def test_entrada_cerrada_no_bloquea(
    db_session: AsyncSession, estado: WaitingListStatus
) -> None:
    s = await make_wait_scene(db_session)
    await make_entry(db_session, s.clinic, s.patient, status=estado, closed_reason="test")
    nueva = await make_entry(db_session, s.clinic, s.patient)

    assert nueva.status is WaitingListStatus.WAITING


@pytest.mark.parametrize(
    ("cambios", "constraint"),
    [
        ({"date_from": date(2030, 2, 1), "date_to": date(2030, 1, 1)}, "date_range"),
        ({"time_from": time(18, 0), "time_to": time(14, 0)}, "time_window"),
        ({"time_from": time(14, 0)}, "time_window"),
        ({"weekdays": [7]}, "weekdays_valid"),
        ({"weekdays": []}, "weekdays_valid"),
        ({"notes": "x" * 201}, "notes_length"),
        ({"consecutive_expired": -1}, "consecutive_expired_nonneg"),
        ({"source": "fax"}, "source_valid"),
    ],
)
async def test_checks_de_la_entrada(
    db_session: AsyncSession, cambios: dict[str, Any], constraint: str
) -> None:
    s = await make_wait_scene(db_session)
    await _falla(db_session, make_entry(db_session, s.clinic, s.patient, **cambios), constraint)


async def test_franja_y_dias_validos(db_session: AsyncSession) -> None:
    s = await make_wait_scene(db_session)
    entry = await make_entry(
        db_session,
        s.clinic,
        s.patient,
        time_from=time(14, 0),
        time_to=time(18, 0),
        weekdays=[1, 3],
        notes="x" * 200,
    )

    assert entry.weekdays == [1, 3]


async def test_prioridad_requiere_motivo(db_session: AsyncSession) -> None:
    s = await make_wait_scene(db_session)
    await _falla(
        db_session,
        make_entry(db_session, s.clinic, s.patient, prioritized_at=INICIO),
        "priority_coherent",
    )


@pytest.mark.parametrize("campo", ["patient", "professional"])
async def test_entrada_con_referencia_de_otra_clinica(db_session: AsyncSession, campo: str) -> None:
    a = await make_wait_scene(db_session)
    b = await make_wait_scene(db_session)
    if campo == "patient":
        coro = make_entry(db_session, a.clinic, b.patient)
    else:
        coro = make_entry(db_session, a.clinic, a.patient, professional=b.professional)
    await _falla(db_session, coro, "fk_waiting_list_entry")


async def test_una_sola_oferta_pendiente_por_entrada(db_session: AsyncSession) -> None:
    s = await make_wait_scene(db_session)
    entry = await make_entry(db_session, s.clinic, s.patient)
    await make_offer(
        db_session, entry, professional=s.professional, chair=s.chair, starts_at=INICIO
    )

    await _falla(
        db_session,
        make_offer(
            db_session,
            entry,
            professional=s.professional,
            chair=s.chair,
            starts_at=INICIO + timedelta(days=1),
        ),
        "uq_waitlist_offer_pending",
    )


async def test_oferta_cerrada_permite_otra_pendiente(db_session: AsyncSession) -> None:
    s = await make_wait_scene(db_session)
    entry = await make_entry(db_session, s.clinic, s.patient)
    await make_offer(
        db_session,
        entry,
        professional=s.professional,
        chair=s.chair,
        starts_at=INICIO,
        status=WaitlistOfferStatus.EXPIRED,
    )
    otra = await make_offer(
        db_session, entry, professional=s.professional, chair=s.chair, starts_at=INICIO
    )

    assert otra.status is WaitlistOfferStatus.PENDING


async def test_aceptada_exige_turno_y_viceversa(db_session: AsyncSession) -> None:
    s = await make_wait_scene(db_session)
    entry = await make_entry(db_session, s.clinic, s.patient)
    await _falla(
        db_session,
        make_offer(
            db_session,
            entry,
            professional=s.professional,
            chair=s.chair,
            starts_at=INICIO,
            status=WaitlistOfferStatus.ACCEPTED,
        ),
        "accepted_has_appointment",
    )
    turno = await make_appointment(
        db_session,
        s.clinic,
        patient=s.patient,
        professional=s.professional,
        chair=s.chair,
        starts_at=INICIO,
    )
    await _falla(
        db_session,
        make_offer(
            db_session,
            entry,
            professional=s.professional,
            chair=s.chair,
            starts_at=INICIO,
            appointment_id=turno.id,
        ),
        "accepted_has_appointment",
    )


@pytest.mark.parametrize(
    ("cambios", "constraint"),
    [
        ({"expires_at": INICIO + timedelta(minutes=1)}, "expires_before_start"),
        ({"ends_at": INICIO}, "range_order"),
        ({"mode": "magic"}, "mode_valid"),
    ],
)
async def test_checks_de_la_oferta(
    db_session: AsyncSession, cambios: dict[str, Any], constraint: str
) -> None:
    s = await make_wait_scene(db_session)
    entry = await make_entry(db_session, s.clinic, s.patient)
    await _falla(
        db_session,
        make_offer(
            db_session,
            entry,
            professional=s.professional,
            chair=s.chair,
            starts_at=INICIO,
            **cambios,
        ),
        constraint,
    )


async def test_oferta_con_recursos_de_otra_clinica(db_session: AsyncSession) -> None:
    a = await make_wait_scene(db_session)
    b = await make_wait_scene(db_session)
    entry = await make_entry(db_session, a.clinic, a.patient)
    await _falla(
        db_session,
        make_offer(db_session, entry, professional=b.professional, chair=a.chair, starts_at=INICIO),
        "fk_waitlist_offer",
    )


async def test_oferta_de_entrada_de_otra_clinica(db_session: AsyncSession) -> None:
    a = await make_wait_scene(db_session)
    b = await make_wait_scene(db_session)
    entry_b = await make_entry(db_session, b.clinic, b.patient)
    await _falla(
        db_session,
        make_offer(
            db_session,
            entry_b,
            professional=a.professional,
            chair=a.chair,
            starts_at=INICIO,
            clinic_id=a.clinic.id,
        ),
        "fk_waitlist_offer",
    )


async def test_evento_es_append_only(db_session: AsyncSession) -> None:
    s = await make_wait_scene(db_session)
    entry = await make_entry(db_session, s.clinic, s.patient)
    evento = WaitlistEvent(
        clinic_id=s.clinic.id,
        entry_id=entry.id,
        event=WaitlistEventType.ENTRY_CREATED,
        actor_type=ActorType.SYSTEM,
        payload={"source": "reception"},
    )
    db_session.add(evento)
    await db_session.flush()

    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(
                update(WaitlistEvent).where(WaitlistEvent.id == evento.id).values(payload={})
            )
    with pytest.raises(DBAPIError, match="append-only"):
        async with db_session.begin_nested():
            await db_session.execute(delete(WaitlistEvent).where(WaitlistEvent.id == evento.id))


async def test_evento_de_usuario_exige_actor(db_session: AsyncSession) -> None:
    s = await make_wait_scene(db_session)
    entry = await make_entry(db_session, s.clinic, s.patient)

    async def _insert() -> None:
        db_session.add(
            WaitlistEvent(
                clinic_id=s.clinic.id,
                entry_id=entry.id,
                event=WaitlistEventType.ENTRY_CREATED,
                actor_type=ActorType.USER,
                payload={},
            )
        )
        await db_session.flush()

    await _falla(db_session, _insert(), "actor_user_coherent")


async def test_otro_paciente_misma_clinica_no_choca(db_session: AsyncSession) -> None:
    s = await make_wait_scene(db_session)
    otro = await make_patient(db_session, s.clinic, full_name="Paciente Ficticio Dos")
    otra_prof = await make_professional(db_session, s.clinic, display_name="Dra. Ficticia Dos")
    await make_entry(db_session, s.clinic, s.patient, professional=otra_prof)
    segunda = await make_entry(db_session, s.clinic, otro, professional=otra_prof)

    assert segunda.id is not None
