"""Estados de entrega informados por Meta (C-10, D6; spec whatsapp-webhook).

Postgres real; POST firmados contra la app; datos ficticios (regla 13).
"""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta

import httpx
import pytest
from app.core.settings import Settings, get_settings
from app.models import (
    DeliveryEventType,
    ReminderJob,
    ReminderReason,
    ReminderStatus,
)
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from tests.reminder_helpers import AHORA, email_ficticio, events_of, jobs_of, make_job, make_scene
from tests.whatsapp_helpers import (
    WEBHOOK,
    encode,
    envelope,
    signed_headers,
    status,
    whatsapp_settings,
)

pytestmark = pytest.mark.integration


@pytest.fixture()
def settings() -> Settings:
    return whatsapp_settings(Settings())  # type: ignore[call-arg]


@pytest.fixture(autouse=True)
def _config(app_instance: FastAPI, settings: Settings) -> None:
    app_instance.dependency_overrides[get_settings] = lambda: settings


def _wamid() -> str:
    return "wamid.FICTICIO-" + secrets.token_hex(8)


async def _post(client: httpx.AsyncClient, *estados: dict[str, object]) -> httpx.Response:
    cuerpo = encode(envelope(statuses=list(estados)))
    return await client.post(WEBHOOK, content=cuerpo, headers=signed_headers(cuerpo))


async def _job_enviado(
    session: AsyncSession, *, email: str | None = None, estado: ReminderStatus = ReminderStatus.SENT
) -> ReminderJob:
    escena = await make_scene(session, opt_in=True, email=email)
    return await make_job(
        session,
        escena.appointment,
        status=estado,
        sent_at=AHORA,
        provider_message_id=_wamid(),
    )


async def _releer(session: AsyncSession, job: ReminderJob) -> ReminderJob:
    return (await jobs_of(session, job.appointment_id))[(job.step, job.channel.value)]


async def _tipos(session: AsyncSession, job: ReminderJob) -> list[DeliveryEventType]:
    return [e.event_type for e in await events_of(session, job.id)]


async def test_entregado_y_leido(app_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    job = await _job_enviado(db_session)
    pid = job.provider_message_id
    assert pid is not None

    assert (await _post(app_client, status(pid, "delivered", AHORA))).status_code == 200
    assert (
        await _post(app_client, status(pid, "read", AHORA + timedelta(minutes=1)))
    ).status_code == 200

    assert (await _releer(db_session, job)).status is ReminderStatus.READ
    assert await _tipos(db_session, job) == [DeliveryEventType.DELIVERED, DeliveryEventType.READ]


async def test_el_evento_guarda_el_instante_de_meta(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    job = await _job_enviado(db_session)
    assert job.provider_message_id is not None
    momento = AHORA + timedelta(minutes=7)

    await _post(app_client, status(job.provider_message_id, "delivered", momento))

    [evento] = await events_of(db_session, job.id)
    assert evento.occurred_at == momento
    assert evento.provider_event_id == f"{job.provider_message_id}:delivered"


async def test_desordenados_no_retroceden(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    job = await _job_enviado(db_session)
    pid = job.provider_message_id
    assert pid is not None

    await _post(app_client, status(pid, "read", AHORA + timedelta(minutes=2)))
    await _post(app_client, status(pid, "delivered", AHORA + timedelta(minutes=1)))

    assert (await _releer(db_session, job)).status is ReminderStatus.READ
    assert sorted(await _tipos(db_session, job)) == sorted(
        [DeliveryEventType.READ, DeliveryEventType.DELIVERED]
    )


async def test_estado_repetido_se_registra_una_vez(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    job = await _job_enviado(db_session)
    pid = job.provider_message_id
    assert pid is not None

    await _post(app_client, status(pid, "delivered", AHORA))
    respuesta = await _post(app_client, status(pid, "delivered", AHORA))

    assert respuesta.status_code == 200
    assert await _tipos(db_session, job) == [DeliveryEventType.DELIVERED]


async def test_estado_de_un_mensaje_desconocido_se_ignora(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    job = await _job_enviado(db_session)

    respuesta = await _post(app_client, status(_wamid(), "delivered", AHORA))

    assert respuesta.status_code == 200
    assert (await _releer(db_session, job)).status is ReminderStatus.SENT
    assert await _tipos(db_session, job) == []


async def test_estado_sent_de_meta_no_duplica_el_evento_del_motor(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    job = await _job_enviado(db_session)
    assert job.provider_message_id is not None

    await _post(app_client, status(job.provider_message_id, "sent", AHORA))

    assert await _tipos(db_session, job) == []


async def test_falla_despues_de_enviado_falla_el_job_y_escala_a_email(
    app_client: httpx.AsyncClient, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    job = await _job_enviado(db_session, email=email_ficticio())
    assert job.provider_message_id is not None
    caplog.set_level(logging.DEBUG)

    respuesta = await _post(
        app_client, status(job.provider_message_id, "failed", AHORA, error_code=131026)
    )

    assert respuesta.status_code == 200
    jobs = await jobs_of(db_session, job.appointment_id)
    fallido = jobs[(job.step, "whatsapp")]
    assert fallido.status is ReminderStatus.FAILED
    assert fallido.reason == ReminderReason.PROVIDER_REJECTED.value
    assert fallido.last_error == "meta_131026"
    assert jobs[(job.step, "email")].status is ReminderStatus.SCHEDULED
    tipos = await _tipos(db_session, job)
    assert DeliveryEventType.FAILED in tipos and DeliveryEventType.ESCALATED in tipos
    assert "5491155550199" not in caplog.text


async def test_falla_sin_email_no_escala(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    job = await _job_enviado(db_session)
    assert job.provider_message_id is not None

    await _post(app_client, status(job.provider_message_id, "failed", AHORA, error_code=131026))

    jobs = await jobs_of(db_session, job.appointment_id)
    assert jobs[(job.step, "whatsapp")].status is ReminderStatus.FAILED
    assert (job.step, "email") not in jobs


async def test_falla_tardia_de_un_entregado_solo_registra_el_evento(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    job = await _job_enviado(db_session, estado=ReminderStatus.DELIVERED)
    assert job.provider_message_id is not None

    await _post(app_client, status(job.provider_message_id, "failed", AHORA, error_code=131000))

    assert (await _releer(db_session, job)).status is ReminderStatus.DELIVERED
    assert await _tipos(db_session, job) == [DeliveryEventType.FAILED]


async def test_los_eventos_no_llevan_datos_del_destinatario(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    job = await _job_enviado(db_session)
    assert job.provider_message_id is not None

    await _post(app_client, status(job.provider_message_id, "failed", AHORA, error_code=131026))

    for evento in await events_of(db_session, job.id):
        assert "5491155550199" not in str(evento.payload)
        assert "recipient" not in str(evento.payload)
