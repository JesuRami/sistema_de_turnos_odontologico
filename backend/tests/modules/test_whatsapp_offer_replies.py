"""Respuestas del paciente a una oferta de lista de espera por WhatsApp (C-12, D8).

Spec `reminders/whatsapp-webhook` (delta de C-12). POST firmados contra la app real; Postgres real.
Reloj en `AHORA` (lunes 07/01/2030 08:00 UTC). Datos ficticios (regla 13).
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import date, time, timedelta
from typing import Any

import httpx
import pytest
from app.common.clock import get_now
from app.core.settings import Settings, get_settings
from app.models import (
    Appointment,
    AppointmentOrigin,
    AppointmentStatus,
    Patient,
    ReminderChannel,
    ReminderJob,
    ReminderStatus,
    WaitingListEntry,
    WaitingListStatus,
    WaitlistOffer,
    WaitlistOfferStatus,
    WhatsAppInbound,
    WhatsAppIntent,
    WhatsAppOutboundReply,
    WhatsAppReplyKind,
)
from app.modules.notifications.replies import render_reply
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import (
    make_appointment,
    make_chair,
    make_clinic,
    make_patient,
    make_professional,
    make_schedule_rule,
)
from tests.reminder_helpers import AHORA
from tests.waitlist_helpers import make_entry, make_offer
from tests.whatsapp_helpers import (
    WEBHOOK,
    button_message,
    encode,
    envelope,
    signed_headers,
    text_message,
    whatsapp_settings,
)

pytestmark = pytest.mark.integration

HUECO = AHORA + timedelta(days=2, hours=5)  # miércoles 09/01 13:00 UTC = 10:00 local


@pytest.fixture()
def settings() -> Settings:
    return whatsapp_settings(Settings())  # type: ignore[call-arg]


@pytest.fixture(autouse=True)
def _config(app_instance: FastAPI, settings: Settings) -> None:
    app_instance.dependency_overrides[get_settings] = lambda: settings
    app_instance.dependency_overrides[get_now] = lambda: AHORA


@dataclass
class Escena:
    paciente: Patient
    entry: WaitingListEntry
    offer: WaitlistOffer
    wamid: str

    @property
    def wa(self) -> str:
        assert self.paciente.phone_e164 is not None
        return self.paciente.phone_e164.removeprefix("+")


async def _escena(db: AsyncSession, **oferta: Any) -> Escena:
    clinic = await make_clinic(db)
    prof = await make_professional(db, clinic)
    chair = await make_chair(db, clinic)
    await make_schedule_rule(
        db, clinic, prof, chair, weekday=2, start_time=time(9), end_time=time(13)
    )
    paciente = await make_patient(db, clinic, whatsapp_opt_in=True)
    entry = await make_entry(
        db,
        clinic,
        paciente,
        status=WaitingListStatus.OFFERED,
        date_from=date(2030, 1, 7),
        date_to=date(2030, 1, 20),
    )
    valores: dict[str, Any] = {"now": AHORA}
    valores.update(oferta)
    offer = await make_offer(db, entry, professional=prof, chair=chair, starts_at=HUECO, **valores)
    wamid = "wamid.OFERTA-" + secrets.token_hex(6)
    db.add(
        ReminderJob(
            clinic_id=clinic.id,
            waitlist_offer_id=offer.id,
            step="waitlist_offer",
            channel=ReminderChannel.WHATSAPP,
            scheduled_for=AHORA,
            available_at=AHORA,
            starts_at_snapshot=HUECO,
            status=ReminderStatus.SENT,
            sent_at=AHORA,
            provider_message_id=wamid,
        )
    )
    await db.flush()
    return Escena(paciente, entry, offer, wamid)


async def _post(client: httpx.AsyncClient, mensaje: dict[str, object]) -> None:
    cuerpo = encode(envelope(messages=[mensaje]))
    r = await client.post(WEBHOOK, content=cuerpo, headers=signed_headers(cuerpo))
    assert r.status_code == 200, r.text


async def _boton(client: httpx.AsyncClient, e: Escena, payload: str, **kw: Any) -> str:
    message_id = kw.pop("message_id", None) or "wamid.IN-" + secrets.token_hex(6)
    await _post(
        client, button_message(e.wa, payload, AHORA, message_id=message_id, context_id=e.wamid)
    )
    return str(message_id)


async def _texto(client: httpx.AsyncClient, e: Escena, texto: str, *, citar: bool = True) -> None:
    await _post(
        client,
        text_message(
            e.wa,
            texto,
            AHORA,
            message_id="wamid.IN-" + secrets.token_hex(6),
            context_id=e.wamid if citar else None,
        ),
    )


async def _respuestas(db: AsyncSession, e: Escena) -> list[WhatsAppReplyKind]:
    return [
        r.kind
        for r in (
            await db.execute(
                select(WhatsAppOutboundReply).where(
                    WhatsAppOutboundReply.patient_id == e.paciente.id
                )
            )
        ).scalars()
    ]


async def _oferta(db: AsyncSession, e: Escena) -> WaitlistOffer:
    await db.refresh(e.offer)
    return e.offer


async def _turnos(db: AsyncSession, e: Escena) -> list[Appointment]:
    return list(
        (
            await db.execute(select(Appointment).where(Appointment.patient_id == e.paciente.id))
        ).scalars()
    )


async def test_boton_tomarlo_crea_el_turno(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    e = await _escena(db_session)

    await _boton(app_client, e, "offer_accept")

    [turno] = await _turnos(db_session, e)
    assert turno.origin is AppointmentOrigin.WAITLIST
    assert (await _oferta(db_session, e)).status is WaitlistOfferStatus.ACCEPTED
    assert await _respuestas(db_session, e) == [WhatsAppReplyKind.OFFER_ACCEPTED]
    entrante = await db_session.scalar(
        select(WhatsAppInbound).where(WhatsAppInbound.patient_id == e.paciente.id)
    )
    assert entrante is not None
    assert entrante.waitlist_offer_id == e.offer.id
    assert entrante.intent is WhatsAppIntent.ACCEPT_OFFER


@pytest.mark.parametrize("texto", ["sí", "Tomarlo"])
async def test_textos_que_aceptan_citando_la_oferta(
    app_client: httpx.AsyncClient, db_session: AsyncSession, texto: str
) -> None:
    e = await _escena(db_session)

    await _texto(app_client, e, texto)

    assert len(await _turnos(db_session, e)) == 1


@pytest.mark.parametrize(
    ("forma", "valor"), [("boton", "offer_decline"), ("texto", "Paso"), ("texto", "no")]
)
async def test_rechazos_citando_la_oferta(
    app_client: httpx.AsyncClient, db_session: AsyncSession, forma: str, valor: str
) -> None:
    e = await _escena(db_session)

    if forma == "boton":
        await _boton(app_client, e, valor)
    else:
        await _texto(app_client, e, valor)

    assert (await _oferta(db_session, e)).status is WaitlistOfferStatus.DECLINED
    await db_session.refresh(e.entry)
    assert e.entry.status is WaitingListStatus.WAITING
    assert await _respuestas(db_session, e) == [WhatsAppReplyKind.OFFER_DECLINED]


async def test_stop_citando_la_oferta(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    e = await _escena(db_session)

    await _texto(app_client, e, "no me escriban más")

    assert (await _oferta(db_session, e)).status is WaitlistOfferStatus.PENDING
    await db_session.refresh(e.paciente)
    assert e.paciente.whatsapp_opt_in is False


async def test_texto_desconocido_no_cambia_la_oferta(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    e = await _escena(db_session)

    await _texto(app_client, e, "¿con quién era?")

    assert (await _oferta(db_session, e)).status is WaitlistOfferStatus.PENDING
    assert await _respuestas(db_session, e) == []


async def _clinica(db: AsyncSession, e: Escena) -> Any:
    from app.models import Clinic

    return await db.get(Clinic, e.offer.clinic_id)


async def test_si_sin_contexto_sigue_el_ruteo_al_turno(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    e = await _escena(db_session)
    clinica = await _clinica(db_session, e)
    turno = await make_appointment(
        db_session,
        clinica,
        patient=e.paciente,
        professional=await make_professional(db_session, clinica),
        chair=await make_chair(db_session, clinica),
        starts_at=AHORA + timedelta(days=5),
        status=AppointmentStatus.PENDING,
        origin=AppointmentOrigin.ONLINE,
    )

    await _texto(app_client, e, "si", citar=False)

    assert (await _oferta(db_session, e)).status is WaitlistOfferStatus.PENDING
    await db_session.refresh(turno)
    assert turno.status is AppointmentStatus.CONFIRMED


async def test_tomarlo_vencida(app_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    e = await _escena(db_session, expires_in=timedelta(minutes=-1))

    await _boton(app_client, e, "offer_accept")

    assert await _turnos(db_session, e) == []
    assert await _respuestas(db_session, e) == [WhatsAppReplyKind.OFFER_CLOSED]


async def test_hueco_ocupado(app_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    e = await _escena(db_session)
    clinica = await _clinica(db_session, e)
    titular = await make_patient(db_session, clinica)
    await make_appointment(
        db_session,
        clinica,
        patient=titular,
        professional=await _prof(db_session, e),
        chair=await _sillon(db_session, e),
        starts_at=HUECO,
    )

    await _boton(app_client, e, "offer_accept")

    assert await _respuestas(db_session, e) == [WhatsAppReplyKind.OFFER_TAKEN]
    await db_session.refresh(e.entry)
    assert e.entry.priority_reason == "slot_lost"


async def _prof(db: AsyncSession, e: Escena) -> Any:
    from app.models import Professional

    return await db.get(Professional, e.offer.professional_id)


async def _sillon(db: AsyncSession, e: Escena) -> Any:
    from app.models import Chair

    return await db.get(Chair, e.offer.chair_id)


async def test_paciente_ocupado(app_client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    e = await _escena(db_session)
    clinica = await _clinica(db_session, e)
    await make_appointment(
        db_session,
        clinica,
        patient=e.paciente,
        professional=await make_professional(db_session, clinica),
        chair=await make_chair(db_session, clinica),
        starts_at=HUECO,
    )

    await _boton(app_client, e, "offer_accept")

    assert await _respuestas(db_session, e) == [WhatsAppReplyKind.OFFER_PATIENT_BUSY]
    assert (await _oferta(db_session, e)).status is WaitlistOfferStatus.PENDING


async def test_reenvio_de_meta_no_duplica(
    app_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    e = await _escena(db_session)

    await _boton(app_client, e, "offer_accept", message_id="wamid.IN-REPETIDO")
    await _boton(app_client, e, "offer_accept", message_id="wamid.IN-REPETIDO")

    assert len(await _turnos(db_session, e)) == 1
    assert await _respuestas(db_session, e) == [WhatsAppReplyKind.OFFER_ACCEPTED]


def test_el_texto_de_la_aceptacion_lleva_fecha_hora_y_link() -> None:
    from zoneinfo import ZoneInfo

    texto = render_reply(
        WhatsAppReplyKind.OFFER_ACCEPTED,
        clinic_name="Clínica Ficticia",
        clinic_phone=None,
        manage_url="http://localhost:5174/g/v1.token-ficticio",
        starts_at=HUECO,
        tz=ZoneInfo("America/Argentina/Buenos_Aires"),
    )

    assert "10:00" in texto
    assert "http://localhost:5174/g/v1.token-ficticio" in texto


@pytest.mark.parametrize(
    "tipo",
    [
        WhatsAppReplyKind.OFFER_DECLINED,
        WhatsAppReplyKind.OFFER_TAKEN,
        WhatsAppReplyKind.OFFER_CLOSED,
        WhatsAppReplyKind.OFFER_PATIENT_BUSY,
    ],
)
def test_textos_de_oferta_sin_datos_del_paciente(tipo: WhatsAppReplyKind) -> None:
    texto = render_reply(
        tipo, clinic_name="Clínica Ficticia", clinic_phone="+5491155550100", manage_url=None
    )

    assert texto.strip()
