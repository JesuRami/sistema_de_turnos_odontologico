"""US-003: bloqueos — objetivo y motivo, inmutabilidad, retiro lógico, cierre, RBAC y auditoría."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from app.core.settings import Settings
from app.models import (
    Appointment,
    AppointmentEvent,
    AppointmentEventType,
    AppointmentStatus,
    Block,
    BlockReason,
    CancellationReason,
    ConfigAction,
    ConfigEntity,
)
from redis.asyncio import Redis
from sqlalchemy import func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.agenda_helpers import Staff, actions, config_events, make_staff
from tests.factories import (
    make_appointment,
    make_block,
    make_chair,
    make_patient,
    make_professional,
)

pytestmark = pytest.mark.integration


def _iso(delta: timedelta) -> str:
    return (datetime.now(UTC) + delta).isoformat()


def _bloqueo(staff: Staff, **overrides: object) -> dict[str, object]:
    valores: dict[str, object] = {
        "professional_id": str(staff.professional.id),
        "starts_at": _iso(timedelta(days=2)),
        "ends_at": _iso(timedelta(days=9)),
        "reason": "vacaciones",
    }
    valores.update(overrides)
    return valores


async def _crear(
    client: httpx.AsyncClient, staff: Staff, rol: str = "admin", **overrides: object
) -> httpx.Response:
    return await client.post(
        "/api/blocks", json=_bloqueo(staff, **overrides), headers=staff.headers[rol]
    )


# ----------------------------------------------------------------------- alta


@pytest.mark.parametrize("rol", ["admin", "recepcion", "odontologo"])
async def test_personal_crea_bloqueo_propio_y_queda_auditado(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    rol: str,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)

    response = await _crear(app_client, staff, rol, notes="Licencia ficticia")

    assert response.status_code == 201
    body = response.json()
    assert body["reason"] == "vacaciones"
    assert body["chair_id"] is None
    assert body["notes"] == "Licencia ficticia"
    eventos = await config_events(db_session, ConfigEntity.BLOCK, uuid.UUID(body["id"]))
    assert actions(eventos) == [ConfigAction.CREATED]


async def test_bloqueo_de_profesional_y_sillon_juntos(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    response = await _crear(app_client, staff, chair_id=str(staff.chair.id), reason="reunion")
    assert response.status_code == 201
    assert response.json()["chair_id"] == str(staff.chair.id)


@pytest.mark.parametrize(
    "invalido",
    [
        {"professional_id": None},
        {"reason": "siesta"},
        {"reason": None},
        {"ends_at": _iso(timedelta(days=1))},
        {"starts_at": "2026-12-01T09:00:00"},
        {"notes": "x" * 501},
        {"clinic_id": str(uuid.uuid4())},
    ],
)
async def test_bloqueo_invalido_es_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    invalido: dict[str, object],
) -> None:
    """Sin objetivo (RN-BL-01), motivo fuera de catálogo, rango invertido o fecha sin zona → 422."""
    staff = await make_staff(db_session, redis_client, settings)
    response = await app_client.post(
        "/api/blocks", json=_bloqueo(staff, **invalido), headers=staff.headers["admin"]
    )
    assert response.status_code == 422


async def test_bloqueo_totalmente_pasado_es_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    response = await _crear(
        app_client, staff, starts_at=_iso(timedelta(days=-3)), ends_at=_iso(timedelta(days=-2))
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "block_in_past"}


async def test_recurso_de_otra_clinica_o_inactivo_es_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    otra = await make_staff(db_session, redis_client, settings)
    inactivo = await make_chair(db_session, staff.clinic, active=False)

    ajeno = await _crear(app_client, staff, professional_id=None, chair_id=str(otra.chair.id))
    apagado = await _crear(app_client, staff, professional_id=None, chair_id=str(inactivo.id))

    assert ajeno.json() == {"detail": "invalid_resource"}
    assert apagado.json() == {"detail": "resource_inactive"}


async def test_odontologo_no_bloquea_a_un_colega_ni_solo_un_sillon(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    colega = await make_professional(db_session, staff.clinic, display_name="Dr. Ficticio Colega")

    a_colega = await _crear(app_client, staff, "odontologo", professional_id=str(colega.id))
    solo_sillon = await _crear(
        app_client, staff, "odontologo", professional_id=None, chair_id=str(staff.chair.id)
    )

    assert a_colega.status_code == 403
    assert a_colega.json() == {"detail": "forbidden_scope"}
    assert solo_sillon.status_code == 403


# -------------------------------------------------------------------- lectura


async def test_listado_por_rango_y_alcance_del_odontologo(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    colega = await make_professional(db_session, staff.clinic, display_name="Dr. Ficticio Colega")
    propio = await make_block(db_session, staff.clinic, professional=staff.professional)
    de_colega = await make_block(db_session, staff.clinic, professional=colega)
    de_sillon = await make_block(db_session, staff.clinic, chair=staff.chair)
    lejano = await make_block(
        db_session, staff.clinic, professional=staff.professional, starts_in=timedelta(days=60)
    )
    rango = {"from": _iso(timedelta(0)), "to": _iso(timedelta(days=30))}

    recepcion = await app_client.get(
        "/api/blocks", params=rango, headers=staff.headers["recepcion"]
    )
    por_sillon = await app_client.get(
        "/api/blocks",
        params={**rango, "chair_id": str(staff.chair.id)},
        headers=staff.headers["recepcion"],
    )
    odontologo = await app_client.get("/api/blocks", headers=staff.headers["odontologo"])
    ajeno = await app_client.get(f"/api/blocks/{de_colega.id}", headers=staff.headers["odontologo"])

    assert {i["id"] for i in recepcion.json()["items"]} == {
        str(propio.id),
        str(de_colega.id),
        str(de_sillon.id),
    }
    assert [i["id"] for i in por_sillon.json()["items"]] == [str(de_sillon.id)]
    assert {i["id"] for i in odontologo.json()["items"]} == {str(propio.id), str(lejano.id)}
    assert ajeno.status_code == 404


async def test_rango_invertido_es_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    response = await app_client.get(
        "/api/blocks",
        params={"from": _iso(timedelta(days=5)), "to": _iso(timedelta(days=1))},
        headers=staff.headers["admin"],
    )
    assert response.status_code == 422


# ------------------------------------------------------- edición y retiro


async def test_admin_edita_bloqueo_futuro_y_audita(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    block = await make_block(db_session, staff.clinic, professional=staff.professional)

    response = await app_client.patch(
        f"/api/blocks/{block.id}",
        json={"reason": "mantenimiento", "notes": "Revisión ficticia"},
        headers=staff.headers["admin"],
    )

    assert response.status_code == 200
    assert response.json()["reason"] == "mantenimiento"
    eventos = await config_events(db_session, ConfigEntity.BLOCK, block.id)
    assert eventos[-1].action is ConfigAction.UPDATED
    assert eventos[-1].changes == {
        "reason": ["vacaciones", "mantenimiento"],
        "notes": [None, "Revisión ficticia"],
    }


async def test_bloqueo_terminado_es_inmutable(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """RN-BL-03: un bloqueo pasado no se edita ni se retira."""
    staff = await make_staff(db_session, redis_client, settings)
    pasado = await make_block(
        db_session,
        staff.clinic,
        chair=staff.chair,
        starts_in=timedelta(days=-3),
        ends_at_delta=timedelta(days=1),
    )

    edicion = await app_client.patch(
        f"/api/blocks/{pasado.id}", json={"notes": "retoque"}, headers=staff.headers["admin"]
    )
    retiro = await app_client.delete(f"/api/blocks/{pasado.id}", headers=staff.headers["admin"])

    assert (edicion.status_code, retiro.status_code) == (409, 409)
    assert edicion.json() == {"detail": "block_immutable"}
    await db_session.refresh(pasado)
    assert (pasado.notes, pasado.removed_at) == (None, None)


async def test_bloqueo_en_curso_solo_admite_mover_el_fin(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    en_curso = await make_block(
        db_session,
        staff.clinic,
        professional=staff.professional,
        starts_in=timedelta(days=-1),
        ends_at_delta=timedelta(days=5),
    )
    url = f"/api/blocks/{en_curso.id}"

    acortar = await app_client.patch(
        url, json={"ends_at": _iso(timedelta(hours=2))}, headers=staff.headers["admin"]
    )
    al_pasado = await app_client.patch(
        url, json={"ends_at": _iso(timedelta(hours=-2))}, headers=staff.headers["admin"]
    )
    motivo = await app_client.patch(url, json={"reason": "otro"}, headers=staff.headers["admin"])
    retiro = await app_client.delete(url, headers=staff.headers["admin"])

    assert acortar.status_code == 200
    assert al_pasado.json() == {"detail": "block_in_past"}
    assert motivo.json() == {"detail": "block_immutable"}
    assert retiro.status_code == 409


async def test_edicion_futura_no_puede_mover_el_inicio_al_pasado(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    block = await make_block(db_session, staff.clinic, professional=staff.professional)

    al_pasado = await app_client.patch(
        f"/api/blocks/{block.id}",
        json={"starts_at": _iso(timedelta(days=-1))},
        headers=staff.headers["admin"],
    )
    invertido = await app_client.patch(
        f"/api/blocks/{block.id}",
        json={"ends_at": _iso(timedelta(hours=1))},
        headers=staff.headers["admin"],
    )

    assert al_pasado.json() == {"detail": "block_in_past"}
    assert invertido.json() == {"detail": "invalid_block_range"}


async def test_admin_retira_bloqueo_futuro_con_baja_logica(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    block = await make_block(db_session, staff.clinic, professional=staff.professional)

    retiro = await app_client.delete(f"/api/blocks/{block.id}", headers=staff.headers["admin"])
    otra_vez = await app_client.delete(f"/api/blocks/{block.id}", headers=staff.headers["admin"])
    listado = await app_client.get("/api/blocks", headers=staff.headers["admin"])

    assert retiro.status_code == 204
    assert otra_vez.status_code == 404
    assert listado.json()["items"] == []
    await db_session.refresh(block)
    assert block.removed_at is not None
    assert block.removed_by_user_id == staff.admin.id
    eventos = await config_events(db_session, ConfigEntity.BLOCK, block.id)
    assert actions(eventos) == [ConfigAction.REMOVED]


@pytest.mark.parametrize("rol", ["recepcion", "odontologo"])
async def test_solo_admin_edita_y_retira(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    rol: str,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    block = await make_block(db_session, staff.clinic, professional=staff.professional)

    edicion = await app_client.patch(
        f"/api/blocks/{block.id}", json={"notes": "x"}, headers=staff.headers[rol]
    )
    retiro = await app_client.delete(f"/api/blocks/{block.id}", headers=staff.headers[rol])

    assert (edicion.status_code, retiro.status_code) == (403, 403)


async def test_admin_de_otra_clinica_no_ve_ni_toca_bloqueos(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    otra = await make_staff(db_session, redis_client, settings)
    block = await make_block(db_session, staff.clinic, chair=staff.chair)

    listado = await app_client.get("/api/blocks", headers=otra.headers["admin"])
    retiro = await app_client.delete(f"/api/blocks/{block.id}", headers=otra.headers["admin"])

    assert listado.json()["items"] == []
    assert retiro.status_code == 404


# ------------------------------------------------------------ cierre de clínica


async def test_cierre_bloquea_cada_sillon_activo_en_una_operacion(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    """RN-BL-04: feriado = un bloqueo por sillón activo; los inactivos no se tocan."""
    staff = await make_staff(db_session, redis_client, settings)
    segundo = await make_chair(db_session, staff.clinic, name="Sillón Ficticio Dos")
    tercero = await make_chair(db_session, staff.clinic, name="Sillón Ficticio Tres")
    await make_chair(db_session, staff.clinic, name="Sillón Ficticio Roto", active=False)

    response = await app_client.post(
        "/api/blocks/closure",
        json={"starts_at": _iso(timedelta(days=10)), "ends_at": _iso(timedelta(days=11))},
        headers=staff.headers["admin"],
    )

    assert response.status_code == 201
    items = response.json()["items"]
    assert {i["chair_id"] for i in items} == {str(staff.chair.id), str(segundo.id), str(tercero.id)}
    assert {i["reason"] for i in items} == {"feriado"}
    assert {i["professional_id"] for i in items} == {None}
    for item in items:
        eventos = await config_events(db_session, ConfigEntity.BLOCK, uuid.UUID(item["id"]))
        assert actions(eventos) == [ConfigAction.CREATED]


@pytest.mark.parametrize("rol", ["recepcion", "odontologo"])
async def test_solo_admin_carga_cierres(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    rol: str,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)

    response = await app_client.post(
        "/api/blocks/closure",
        json={"starts_at": _iso(timedelta(days=10)), "ends_at": _iso(timedelta(days=11))},
        headers=staff.headers[rol],
    )

    assert response.status_code == 403
    total = await db_session.scalar(
        select(func.count()).select_from(Block).where(Block.clinic_id == staff.clinic.id)
    )
    assert total == 0


async def test_cierre_sin_sillones_activos_es_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    staff.chair.active = False
    await db_session.flush()

    response = await app_client.post(
        "/api/blocks/closure",
        json={
            "starts_at": _iso(timedelta(days=10)),
            "ends_at": _iso(timedelta(days=11)),
            "reason": BlockReason.OTRO.value,
        },
        headers=staff.headers["admin"],
    )

    assert response.json() == {"detail": "no_active_chairs"}


# ------------------------------------------- RN-BL-02: bloqueos sobre turnos (C-05)


async def _turno(
    db_session: AsyncSession, staff: Staff, inicio: timedelta, **overrides: object
) -> Appointment:
    """Turno sintético persistido directo, `inicio` desde ahora."""
    valores: dict[str, object] = {
        "patient": await make_patient(db_session, staff.clinic),
        "professional": staff.professional,
        "chair": staff.chair,
        "created_by_user_id": staff.admin.id,
    }
    valores.update(overrides)
    return await make_appointment(
        db_session,
        staff.clinic,
        starts_at=datetime.now(UTC) + inicio,
        **valores,  # type: ignore[arg-type]
    )


def _id(entidad: object) -> object:
    """Identidad persistida sin IO: sobrevive a un `expire_all` previo."""
    estado = inspect(entidad)
    assert estado is not None and estado.identity is not None
    return estado.identity[0]


async def _bloqueos(db_session: AsyncSession, staff: Staff) -> int:
    total = await db_session.scalar(
        select(func.count()).select_from(Block).where(Block.clinic_id == _id(staff.clinic))
    )
    return int(total or 0)


async def _estado(db_session: AsyncSession, appointment: Appointment) -> AppointmentStatus:
    appointment_id = _id(appointment)
    db_session.expire_all()
    releido = await db_session.get(Appointment, appointment_id)
    assert releido is not None
    return releido.status


async def test_bloqueo_sobre_un_turno_vigente_es_409_y_no_persiste(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    turno = await _turno(db_session, staff, timedelta(days=3))

    response = await _crear(app_client, staff, "recepcion")

    assert response.status_code == 409
    assert response.json() == {"detail": "block_conflicts", "appointments": [str(turno.id)]}
    assert await _bloqueos(db_session, staff) == 0


async def test_bloqueo_con_resolucion_explicita_cancela_y_bloquea(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    turno = await _turno(db_session, staff, timedelta(days=3))
    turno_id = turno.id
    pendiente = await _turno(db_session, staff, timedelta(days=4), status=AppointmentStatus.PENDING)

    response = await _crear(
        app_client,
        staff,
        cancel_appointments=[
            {"appointment_id": str(turno.id), "reason": "bloqueo", "note": "Licencia"},
            {"appointment_id": str(pendiente.id), "reason": "profesional"},
        ],
    )

    assert response.status_code == 201, response.text
    assert await _estado(db_session, turno) == AppointmentStatus.CANCELLED
    assert await _estado(db_session, pendiente) == AppointmentStatus.CANCELLED
    evento = (
        await db_session.execute(
            select(AppointmentEvent).where(AppointmentEvent.appointment_id == turno_id)
        )
    ).scalar_one()
    assert evento.event == AppointmentEventType.CANCELLED
    assert evento.payload["block_id"] == response.json()["id"]
    assert evento.payload["reason"] == "bloqueo"
    assert await _bloqueos(db_session, staff) == 1


async def test_resolucion_incompleta_es_409_y_no_persiste_nada(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    primero = await _turno(db_session, staff, timedelta(days=3))
    segundo = await _turno(db_session, staff, timedelta(days=5))

    response = await _crear(
        app_client,
        staff,
        cancel_appointments=[{"appointment_id": str(primero.id), "reason": "bloqueo"}],
    )

    assert response.status_code == 409
    assert response.json()["appointments"] == [str(segundo.id)]
    assert await _estado(db_session, primero) == AppointmentStatus.CONFIRMED
    assert await _bloqueos(db_session, staff) == 0


async def test_cancelar_un_turno_no_afectado_es_422(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    afuera = await _turno(db_session, staff, timedelta(days=20))

    response = await _crear(
        app_client,
        staff,
        cancel_appointments=[{"appointment_id": str(afuera.id), "reason": "bloqueo"}],
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_cancellation"
    assert await _estado(db_session, afuera) == AppointmentStatus.CONFIRMED


async def test_turnos_terminados_no_piden_resolucion(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    await _turno(
        db_session,
        staff,
        timedelta(days=3),
        status=AppointmentStatus.CANCELLED,
        cancelled_at=datetime.now(UTC),
        cancellation_reason=CancellationReason.PACIENTE,
    )
    await _turno(db_session, staff, timedelta(days=4), status=AppointmentStatus.NO_SHOW)

    response = await _crear(app_client, staff)

    assert response.status_code == 201, response.text


async def test_odontologo_no_cancela_turnos_con_su_bloqueo(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    turno = await _turno(db_session, staff, timedelta(days=3))

    con_cancelacion = await _crear(
        app_client,
        staff,
        "odontologo",
        cancel_appointments=[{"appointment_id": str(turno.id), "reason": "profesional"}],
    )
    sin_cancelacion = await _crear(app_client, staff, "odontologo")

    assert con_cancelacion.status_code == 403
    assert con_cancelacion.json()["detail"] == "forbidden_role"
    assert sin_cancelacion.status_code == 409
    assert await _estado(db_session, turno) == AppointmentStatus.CONFIRMED


async def test_bloqueo_de_sillon_afecta_turnos_de_cualquier_profesional(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    colega = await make_professional(db_session, staff.clinic, display_name="Dra. Sillón")
    turno = await _turno(db_session, staff, timedelta(days=3), professional=colega)

    response = await _crear(
        app_client,
        staff,
        professional_id=None,
        chair_id=str(staff.chair.id),
        reason="mantenimiento",
    )

    assert response.status_code == 409
    assert response.json()["appointments"] == [str(turno.id)]


async def test_editar_bloqueo_sobre_un_turno_exige_resolucion(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    block = await make_block(
        db_session,
        staff.clinic,
        professional=staff.professional,
        starts_in=timedelta(days=2),
        ends_at_delta=timedelta(days=1),
    )
    turno = await _turno(db_session, staff, timedelta(days=4))
    ruta = f"/api/blocks/{block.id}"
    nuevo_fin = _iso(timedelta(days=6))

    sin = await app_client.patch(ruta, json={"ends_at": nuevo_fin}, headers=staff.headers["admin"])
    con = await app_client.patch(
        ruta,
        json={
            "ends_at": nuevo_fin,
            "cancel_appointments": [{"appointment_id": str(turno.id), "reason": "bloqueo"}],
        },
        headers=staff.headers["admin"],
    )

    assert sin.status_code == 409
    assert sin.json()["appointments"] == [str(turno.id)]
    assert con.status_code == 200, con.text
    assert await _estado(db_session, turno) == AppointmentStatus.CANCELLED


async def test_cierre_de_clinica_sobre_turnos_exige_resolucion(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
) -> None:
    staff = await make_staff(db_session, redis_client, settings)
    turno = await _turno(db_session, staff, timedelta(days=10, hours=2))
    cierre = {"starts_at": _iso(timedelta(days=10)), "ends_at": _iso(timedelta(days=11))}

    sin = await app_client.post("/api/blocks/closure", json=cierre, headers=staff.headers["admin"])
    con = await app_client.post(
        "/api/blocks/closure",
        json={
            **cierre,
            "cancel_appointments": [{"appointment_id": str(turno.id), "reason": "clinica"}],
        },
        headers=staff.headers["admin"],
    )

    assert sin.status_code == 409
    assert con.status_code == 201, con.text
    assert await _estado(db_session, turno) == AppointmentStatus.CANCELLED
