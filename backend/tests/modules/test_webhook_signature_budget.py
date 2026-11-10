"""Cupo de firmas inválidas del webhook de Meta (C-14, D5). Postgres y Redis reales.

Meta no se limita (un 429 provoca reintentos en ráfaga), pero quien manda firmas inválidas sí:
agotado el cupo por IP, el POST responde 429 sin verificar la firma. Una firma válida no consume.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from app.core.settings import Settings, get_settings
from fastapi import FastAPI

from tests.whatsapp_helpers import WEBHOOK, encode, envelope, signed_headers, whatsapp_settings

pytestmark = pytest.mark.integration


@pytest.fixture()
def settings() -> Settings:
    base = Settings()  # type: ignore[call-arg]
    return whatsapp_settings(base, WEBHOOK_INVALID_SIGNATURE_RATE_LIMIT="2/60s")


@pytest.fixture(autouse=True)
def _misma_configuracion(app_instance: FastAPI, settings: Settings) -> None:
    app_instance.dependency_overrides[get_settings] = lambda: settings


def _invalida() -> dict[str, str]:
    return {"X-Hub-Signature-256": "sha256=" + "0" * 64, "Content-Type": "application/json"}


async def test_agotado_el_cupo_de_firmas_invalidas_responde_429(
    client_factory: Callable[..., httpx.AsyncClient],
) -> None:
    cuerpo = encode(envelope())
    async with client_factory("10.1.1.1") as atacante, client_factory("10.1.1.2") as meta:
        primeras = [
            (await atacante.post(WEBHOOK, content=cuerpo, headers=_invalida())) for _ in range(2)
        ]
        bloqueada = await atacante.post(WEBHOOK, content=cuerpo, headers=_invalida())
        legitima = await meta.post(WEBHOOK, content=cuerpo, headers=signed_headers(cuerpo))

    assert [r.status_code for r in primeras] == [401, 401]
    assert bloqueada.status_code == 429
    assert bloqueada.json() == {"detail": "rate_limited"}
    assert int(bloqueada.headers["retry-after"]) >= 1
    # Otra IP con firma válida no se ve afectada.
    assert legitima.status_code == 200


async def test_las_firmas_validas_no_consumen_cupo(
    client_factory: Callable[..., httpx.AsyncClient],
) -> None:
    cuerpo = encode(envelope())
    async with client_factory("10.1.1.3") as meta:
        respuestas = [
            await meta.post(WEBHOOK, content=cuerpo, headers=signed_headers(cuerpo))
            for _ in range(5)
        ]
    assert {r.status_code for r in respuestas} == {200}
