"""Reporte de conversión de la lista de espera (C-12, D9; spec waitlist/conversion-report).

Postgres y Redis reales; eventos sembrados directo, como los escribiría el motor. El reporte se
calcula sobre `waitlist_event`, nunca sobre el estado mutable de ofertas. Datos ficticios
(regla 13).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from app.core.settings import Settings
from app.models import (
    ActorType,
    Professional,
    WaitlistEvent,
    WaitlistEventType,
    WaitlistOffer,
    WaitlistOfferStatus,
)
from redis.asyncio import Redis
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.agenda_helpers import Staff, make_staff
from tests.factories import make_patient, make_professional
from tests.waitlist_helpers import make_entry, make_offer

pytestmark = pytest.mark.integration

URL = "/api/reports/waitlist"
ENERO = {"from": "2030-01-01", "to": "2030-01-31"}
BASE = datetime(2030, 1, 10, 15, 0, tzinfo=UTC)


class Sembrador:
    def __init__(self, db: AsyncSession, staff: Staff) -> None:
        self.db = db
        self.staff = staff
        self.n = 0

    async def oferta(
        self,
        *eventos: WaitlistEventType,
        professional: Professional | None = None,
        mode: str = "auto",
        creada: datetime = BASE,
    ) -> WaitlistOffer:
        """Oferta con `offer_created` en `creada` y los eventos terminales que se pidan."""
        self.n += 1
        prof = professional or self.staff.professional
        paciente = await make_patient(self.db, self.staff.clinic)
        entry = await make_entry(self.db, self.staff.clinic, paciente)
        offer = await make_offer(
            self.db,
            entry,
            professional=prof,
            chair=self.staff.chair,
            starts_at=creada + timedelta(days=3, hours=self.n),
            now=creada,
            mode=mode,
        )
        payload: dict[str, Any] = {
            "professional_id": str(prof.id),
            "chair_id": str(self.staff.chair.id),
            "mode": mode,
        }
        for i, tipo in enumerate((WaitlistEventType.OFFER_CREATED, *eventos)):
            self.db.add(
                WaitlistEvent(
                    clinic_id=self.staff.clinic.id,
                    entry_id=entry.id,
                    offer_id=offer.id,
                    event=tipo,
                    actor_type=ActorType.SYSTEM,
                    payload=payload,
                    created_at=creada + timedelta(minutes=i),
                )
            )
        await self.db.flush()
        return offer


async def _escena(db: AsyncSession, redis: Redis, settings: Settings) -> tuple[Staff, Sembrador]:
    staff = await make_staff(db, redis, settings)
    return staff, Sembrador(db, staff)


def _fila(cuerpo: dict[str, Any], professional_id: Any) -> dict[str, Any]:
    return next(f for f in cuerpo["rows"] if f["professional_id"] == str(professional_id))


async def test_rotacion_que_convierte(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    staff, s = await _escena(db_session, redis_client, settings)
    await s.oferta(WaitlistEventType.OFFER_EXPIRED)
    await s.oferta(WaitlistEventType.OFFER_ACCEPTED, creada=BASE + timedelta(hours=5))

    r = await app_client.get(URL, params=ENERO, headers=staff.headers["admin"])

    assert r.status_code == 200, r.text
    fila = _fila(r.json(), staff.professional.id)
    assert (fila["created"], fila["expired"], fila["accepted"]) == (2, 1, 1)
    assert fila["conversion_pct"] == 50.0
    assert r.json()["totals"]["created"] == 2


async def test_sin_ofertas_ceros_y_tasa_nula(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    staff, _ = await _escena(db_session, redis_client, settings)

    cuerpo = (await app_client.get(URL, params=ENERO, headers=staff.headers["admin"])).json()

    fila = _fila(cuerpo, staff.professional.id)
    assert fila["created"] == fila["accepted"] == 0
    assert fila["conversion_pct"] is None
    assert cuerpo["totals"]["conversion_pct"] is None


async def test_manuales_pendientes_y_cerradas(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    staff, s = await _escena(db_session, redis_client, settings)
    await s.oferta(mode="manual")  # pendiente: solo cuenta en creadas
    await s.oferta(WaitlistEventType.OFFER_DECLINED)
    await s.oferta(WaitlistEventType.OFFER_CANCELLED)

    cuerpo = (await app_client.get(URL, params=ENERO, headers=staff.headers["admin"])).json()

    fila = _fila(cuerpo, staff.professional.id)
    assert (fila["created"], fila["auto"], fila["manual"]) == (3, 2, 1)
    assert (fila["declined"], fila["cancelled"], fila["accepted"], fila["expired"]) == (1, 1, 0, 0)
    assert fila["conversion_pct"] == 0.0


async def test_por_profesional_y_total(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    staff, s = await _escena(db_session, redis_client, settings)
    otra = await make_professional(db_session, staff.clinic, display_name="Dra. Ficticia Dos")
    await s.oferta(WaitlistEventType.OFFER_ACCEPTED)
    await s.oferta(WaitlistEventType.OFFER_ACCEPTED, professional=otra)
    await s.oferta(WaitlistEventType.OFFER_EXPIRED, professional=otra)

    cuerpo = (await app_client.get(URL, params=ENERO, headers=staff.headers["admin"])).json()

    assert _fila(cuerpo, otra.id)["conversion_pct"] == 50.0
    assert _fila(cuerpo, otra.id)["professional_name"] == "Dra. Ficticia Dos"
    assert cuerpo["totals"]["created"] == 3
    assert cuerpo["totals"]["accepted"] == 2
    assert cuerpo["totals"]["conversion_pct"] == 66.7


async def test_fuera_del_rango_no_cuenta(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    staff, s = await _escena(db_session, redis_client, settings)
    await s.oferta(WaitlistEventType.OFFER_ACCEPTED, creada=BASE + timedelta(days=40))

    cuerpo = (await app_client.get(URL, params=ENERO, headers=staff.headers["admin"])).json()

    assert cuerpo["totals"]["created"] == 0


async def test_estado_mutado_sin_evento_no_cambia(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    staff, s = await _escena(db_session, redis_client, settings)
    oferta = await s.oferta(WaitlistEventType.OFFER_EXPIRED)
    antes = (await app_client.get(URL, params=ENERO, headers=staff.headers["admin"])).json()
    await db_session.execute(
        update(WaitlistOffer)
        .where(WaitlistOffer.id == oferta.id)
        .values(status=WaitlistOfferStatus.DECLINED)
    )

    despues = (await app_client.get(URL, params=ENERO, headers=staff.headers["admin"])).json()

    assert antes == despues


@pytest.mark.parametrize("rol", ["recepcion", "odontologo"])
async def test_solo_admin(
    app_client: httpx.AsyncClient,
    db_session: AsyncSession,
    redis_client: Redis,
    settings: Settings,
    rol: str,
) -> None:
    staff, _ = await _escena(db_session, redis_client, settings)

    r = await app_client.get(URL, params=ENERO, headers=staff.headers[rol])

    assert r.status_code == 403
    assert r.json()["detail"] == "forbidden_role"


@pytest.mark.parametrize(
    ("params", "detalle"),
    [
        ({"from": "2030-02-01", "to": "2030-01-01"}, "invalid_range"),
        ({"from": "2029-01-01", "to": "2030-01-02"}, "range_too_large"),
        ({**ENERO, "otro": "x"}, "unknown_parameter"),
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

    r = await app_client.get(URL, params=params, headers=staff.headers["admin"])

    assert r.status_code == 422
    assert r.json()["detail"] == detalle


async def test_csv_con_fila_total_y_formulas_neutralizadas(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    staff, s = await _escena(db_session, redis_client, settings)
    formula = await make_professional(db_session, staff.clinic, display_name="=Dra. Fórmula")
    await s.oferta(WaitlistEventType.OFFER_ACCEPTED, professional=formula)

    r = await app_client.get(URL, params={**ENERO, "format": "csv"}, headers=staff.headers["admin"])

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    texto = r.content.decode("utf-8-sig")
    lineas = texto.strip().splitlines()
    assert lineas[0].startswith("professional_id,professional_name,created")
    assert lineas[-1].startswith("total,")
    assert "'=Dra. Fórmula" in texto


async def test_aislamiento(
    app_client: httpx.AsyncClient, db_session: AsyncSession, redis_client: Redis, settings: Settings
) -> None:
    a, _ = await _escena(db_session, redis_client, settings)
    _, sb = await _escena(db_session, redis_client, settings)
    await sb.oferta(WaitlistEventType.OFFER_ACCEPTED)

    cuerpo = (await app_client.get(URL, params=ENERO, headers=a.headers["admin"])).json()

    assert cuerpo["totals"]["created"] == 0
