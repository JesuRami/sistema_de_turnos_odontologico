"""Reporte de mensajes y costo por paso (C-10, D10; spec reminders/delivery-report).

Postgres y Redis reales; eventos de entrega sembrados directo (como los escribirían el motor y el
webhook). Datos ficticios (regla 13).
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from app.core.settings import Settings
from app.models import (
    DeliveryEvent,
    DeliveryEventType,
    Patient,
    ReminderChannel,
    ReminderJob,
    ReminderStatus,
)
from redis.asyncio import Redis
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.agenda_helpers import Staff, make_staff
from tests.factories import make_appointment, make_patient

pytestmark = pytest.mark.integration

URL = "/api/reports/whatsapp"
ENERO = {"from": "2030-01-01", "to": "2030-01-31"}
BASE = datetime(2030, 1, 10, 15, 0, tzinfo=UTC)
NOMBRE = "Paciente Reporte Ficticio"


class Sembrador:
    """Crea turnos y jobs enviados con sus eventos, sin solaparse en la agenda."""

    def __init__(self, session: AsyncSession, staff: Staff, patient: Patient) -> None:
        self.session = session
        self.staff = staff
        self.patient = patient
        self.n = 0

    async def enviado(
        self,
        step: str,
        sent_at: datetime,
        *,
        channel: ReminderChannel = ReminderChannel.WHATSAPP,
        cost: int | None = 12500,
        then: tuple[DeliveryEventType, ...] = (),
    ) -> ReminderJob:
        self.n += 1
        clinica = self.staff.clinic
        turno = await make_appointment(
            self.session,
            clinica,
            patient=self.patient,
            professional=self.staff.professional,
            chair=self.staff.chair,
            starts_at=BASE + timedelta(days=60, hours=self.n),
        )
        job = ReminderJob(
            clinic_id=clinica.id,
            appointment_id=turno.id,
            step=step,
            channel=channel,
            scheduled_for=sent_at,
            available_at=sent_at,
            starts_at_snapshot=turno.starts_at,
            status=ReminderStatus.SENT,
            sent_at=sent_at,
            provider_message_id="wamid.REPORTE-" + secrets.token_hex(6),
            cost_micros=cost,
        )
        self.session.add(job)
        await self.session.flush()
        payload: dict[str, Any] = {"attempt": 1, "kind": "template"}
        if cost is not None:
            payload["cost_micros"] = cost
        eventos = [(DeliveryEventType.SENT, sent_at, payload)] + [
            (tipo, sent_at + timedelta(minutes=i + 1), {"source": "meta"})
            for i, tipo in enumerate(then)
        ]
        for tipo, momento, datos in eventos:
            self.session.add(
                DeliveryEvent(
                    clinic_id=clinica.id,
                    reminder_job_id=job.id,
                    event_type=tipo,
                    payload=datos,
                    occurred_at=momento,
                )
            )
        await self.session.flush()
        return job


async def _escena(db: AsyncSession, redis: Redis, settings: Settings) -> tuple[Staff, Sembrador]:
    staff = await make_staff(db, redis, settings)
    paciente = await make_patient(db, staff.clinic, full_name=NOMBRE)
    return staff, Sembrador(db, staff, paciente)


def _fila(cuerpo: dict[str, Any], step: str, channel: str = "whatsapp") -> dict[str, Any]:
    return next(f for f in cuerpo["rows"] if f["step"] == step and f["channel"] == channel)


async def test_mezcla_de_estados_por_paso(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    staff, s = await _escena(db_session, redis_client, settings)
    await s.enviado("t_24h", BASE, then=(DeliveryEventType.DELIVERED, DeliveryEventType.READ))
    await s.enviado("t_24h", BASE, then=(DeliveryEventType.DELIVERED,))
    await s.enviado("t_24h", BASE, then=(DeliveryEventType.FAILED,))

    respuesta = await app_client.get(URL, params=ENERO, headers=staff.headers["admin"])

    assert respuesta.status_code == 200, respuesta.text
    fila = _fila(respuesta.json(), "t_24h")
    assert (fila["sent"], fila["delivered"], fila["read"], fila["failed"]) == (3, 2, 1, 1)


async def test_solo_leido_cuenta_como_entregado(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    staff, s = await _escena(db_session, redis_client, settings)
    await s.enviado("t_3h", BASE, then=(DeliveryEventType.READ,))

    cuerpo = (await app_client.get(URL, params=ENERO, headers=staff.headers["admin"])).json()

    fila = _fila(cuerpo, "t_3h")
    assert (fila["sent"], fila["delivered"], fila["read"]) == (1, 1, 1)


async def test_pasos_y_canales_sin_envios_aparecen_en_cero(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    staff, _ = await _escena(db_session, redis_client, settings)

    cuerpo = (await app_client.get(URL, params=ENERO, headers=staff.headers["admin"])).json()

    claves = [(f["step"], f["channel"]) for f in cuerpo["rows"]]
    assert claves == [
        (paso, canal)
        for paso in ("created", "t_72h", "t_24h", "t_3h")
        for canal in ("whatsapp", "email")
    ]
    assert all(f["sent"] == 0 and f["cost_usd"] == "0.000000" for f in cuerpo["rows"])
    assert cuerpo["totals"]["sent"] == 0


async def test_costo_por_paso_y_total(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    staff, s = await _escena(db_session, redis_client, settings)
    await s.enviado("t_24h", BASE, cost=12500)
    await s.enviado("t_24h", BASE, cost=12500)
    await s.enviado("created", BASE, channel=ReminderChannel.EMAIL, cost=None)

    cuerpo = (await app_client.get(URL, params=ENERO, headers=staff.headers["admin"])).json()

    assert _fila(cuerpo, "t_24h")["cost_usd"] == "0.025000"
    assert _fila(cuerpo, "created", "email")["cost_usd"] == "0.000000"
    assert _fila(cuerpo, "created", "email")["sent"] == 1
    assert cuerpo["totals"] == {
        "sent": 3,
        "delivered": 0,
        "read": 0,
        "failed": 0,
        "cost_usd": "0.025000",
    }
    assert cuerpo["currency"] == "USD"


async def test_borde_del_dia_local(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    staff, s = await _escena(db_session, redis_client, settings)
    # 23:30 del 31/10 en Buenos Aires (UTC-3) = 02:30 UTC del 1/11.
    await s.enviado("t_24h", datetime(2030, 11, 1, 2, 30, tzinfo=UTC))

    octubre = (
        await app_client.get(
            URL, params={"from": "2030-10-01", "to": "2030-10-31"}, headers=staff.headers["admin"]
        )
    ).json()
    noviembre = (
        await app_client.get(
            URL, params={"from": "2030-11-01", "to": "2030-11-30"}, headers=staff.headers["admin"]
        )
    ).json()

    assert _fila(octubre, "t_24h")["sent"] == 1
    assert _fila(noviembre, "t_24h")["sent"] == 0


async def test_estado_mutado_sin_evento_no_cambia_el_reporte(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    staff, s = await _escena(db_session, redis_client, settings)
    job = await s.enviado("t_24h", BASE)
    antes = (await app_client.get(URL, params=ENERO, headers=staff.headers["admin"])).json()

    await db_session.execute(
        update(ReminderJob).where(ReminderJob.id == job.id).values(status=ReminderStatus.READ)
    )

    despues = (await app_client.get(URL, params=ENERO, headers=staff.headers["admin"])).json()
    assert despues == antes


async def test_aislamiento_entre_clinicas(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    staff, s = await _escena(db_session, redis_client, settings)
    otra = await make_staff(db_session, redis_client, settings)
    await s.enviado("t_24h", BASE)
    otro_sembrador = Sembrador(db_session, otra, await make_patient(db_session, otra.clinic))
    await otro_sembrador.enviado("t_24h", BASE)
    await otro_sembrador.enviado("t_24h", BASE)

    cuerpo = (await app_client.get(URL, params=ENERO, headers=staff.headers["admin"])).json()

    assert _fila(cuerpo, "t_24h")["sent"] == 1


@pytest.mark.parametrize("rol", ["recepcion", "odontologo"])
async def test_solo_admin(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    rol: str,
) -> None:
    staff, _ = await _escena(db_session, redis_client, settings)

    respuesta = await app_client.get(URL, params=ENERO, headers=staff.headers[rol])

    assert (respuesta.status_code, respuesta.json()["detail"]) == (403, "forbidden_role")


async def test_sin_sesion_es_401(app_client: httpx.AsyncClient) -> None:
    assert (await app_client.get(URL, params=ENERO)).status_code == 401


@pytest.mark.parametrize(
    ("params", "detalle"),
    [
        ({"from": "2030-02-01", "to": "2030-01-01"}, "invalid_range"),
        ({"from": "2030-01-01", "to": "2031-06-01"}, "range_too_large"),
        ({**ENERO, "clinic_id": "x"}, "unknown_parameter"),
        ({**ENERO, "format": "xml"}, "invalid_format"),
    ],
)
async def test_parametros_invalidos(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    params: dict[str, str],
    detalle: str,
) -> None:
    staff, _ = await _escena(db_session, redis_client, settings)

    respuesta = await app_client.get(URL, params=params, headers=staff.headers["admin"])

    assert (respuesta.status_code, respuesta.json()["detail"]) == (422, detalle)


async def test_csv_con_las_mismas_cifras_y_sin_pii(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    staff, s = await _escena(db_session, redis_client, settings)
    job = await s.enviado("t_24h", BASE, then=(DeliveryEventType.DELIVERED,))
    json_ = (await app_client.get(URL, params=ENERO, headers=staff.headers["admin"])).json()

    respuesta = await app_client.get(
        URL, params={**ENERO, "format": "csv"}, headers=staff.headers["admin"]
    )

    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith("text/csv")
    assert "attachment" in respuesta.headers["content-disposition"]
    lineas = respuesta.text.lstrip("﻿").strip().splitlines()
    assert lineas[0] == "step,channel,sent,delivered,read,failed,cost_usd"
    assert len(lineas) == 1 + len(json_["rows"]) + 1
    assert "t_24h,whatsapp,1,1,0,0,0.012500" in lineas
    assert lineas[-1] == "total,,1,1,0,0,0.012500"
    assert NOMBRE.split()[0] not in respuesta.text
    assert job.provider_message_id is not None and job.provider_message_id not in respuesta.text


# ------------------------------------------------------------ reenvío manual (C-11, D9)


async def _reenvio(
    db: AsyncSession, job: ReminderJob, momento: datetime, *, cost: int | None = 12500
) -> None:
    """Segundo `sent` del mismo job, como lo registra el worker tras un reenvío manual."""
    payload: dict[str, Any] = {"attempt": 1, "kind": "template", "manual": True}
    if cost is not None:
        payload["cost_micros"] = cost
    db.add(
        DeliveryEvent(
            clinic_id=job.clinic_id,
            reminder_job_id=job.id,
            event_type=DeliveryEventType.SENT,
            payload=payload,
            occurred_at=momento,
        )
    )
    await db.flush()


async def _evento(
    db: AsyncSession, job: ReminderJob, tipo: DeliveryEventType, momento: datetime
) -> None:
    db.add(
        DeliveryEvent(
            clinic_id=job.clinic_id,
            reminder_job_id=job.id,
            event_type=tipo,
            payload={"source": "meta"},
            occurred_at=momento,
        )
    )
    await db.flush()


async def test_reenvio_manual_entregado_cuenta_dos_envios_y_ningun_fallido(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    staff, s = await _escena(db_session, redis_client, settings)
    job = await s.enviado("t_24h", BASE, then=(DeliveryEventType.FAILED,))
    await _reenvio(db_session, job, BASE + timedelta(hours=1))
    await _evento(
        db_session, job, DeliveryEventType.DELIVERED, BASE + timedelta(hours=1, minutes=1)
    )

    cuerpo = (await app_client.get(URL, params=ENERO, headers=staff.headers["admin"])).json()

    fila = _fila(cuerpo, "t_24h")
    assert (fila["sent"], fila["delivered"], fila["read"], fila["failed"]) == (2, 1, 0, 0)
    assert fila["cost_usd"] == "0.025000"
    assert cuerpo["totals"]["sent"] == 2


async def test_reenvio_manual_sin_entrega_no_cuenta_el_fallo_anterior(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    staff, s = await _escena(db_session, redis_client, settings)
    job = await s.enviado("t_24h", BASE, then=(DeliveryEventType.FAILED,))
    await _reenvio(db_session, job, BASE + timedelta(hours=1))

    fila = _fila(
        (await app_client.get(URL, params=ENERO, headers=staff.headers["admin"])).json(), "t_24h"
    )

    assert (fila["sent"], fila["delivered"], fila["read"], fila["failed"]) == (2, 0, 0, 0)


async def test_reenvio_reencolado_sin_enviar_no_suma_envios_ni_costo(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    staff, s = await _escena(db_session, redis_client, settings)
    await s.enviado("t_24h", BASE, then=(DeliveryEventType.FAILED,))

    fila = _fila(
        (await app_client.get(URL, params=ENERO, headers=staff.headers["admin"])).json(), "t_24h"
    )

    assert (fila["sent"], fila["failed"], fila["cost_usd"]) == (1, 1, "0.012500")


async def test_fallo_de_meta_del_mismo_segundo_que_el_envio_cuenta(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    # Meta informa en segundos: un `failed` del mismo segundo que el último `sent` cuenta.
    staff, s = await _escena(db_session, redis_client, settings)
    job = await s.enviado("t_3h", BASE + timedelta(milliseconds=700))
    await _evento(db_session, job, DeliveryEventType.FAILED, BASE)

    fila = _fila(
        (await app_client.get(URL, params=ENERO, headers=staff.headers["admin"])).json(), "t_3h"
    )

    assert fila["failed"] == 1
