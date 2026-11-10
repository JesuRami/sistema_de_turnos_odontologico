"""Credencial firmada de la oferta (C-12, D6; spec waitlist/offer-link). Unitario, sin base."""

from __future__ import annotations

import uuid

import pytest
from app.modules.reminders.links import ManageLinkDisabled, sign_manage_token, verify_manage_token
from app.modules.waiting_list.links import sign_offer_token, verify_offer_token

SECRETO = "firma-de-links-solo-para-tests-32-bytes-ok"


def test_ida_y_vuelta() -> None:
    oferta = uuid.uuid4()
    token = sign_offer_token(SECRETO, oferta)

    assert token.startswith("w1.")
    assert verify_offer_token(SECRETO, token) == oferta


def test_es_estable() -> None:
    oferta = uuid.uuid4()

    assert sign_offer_token(SECRETO, oferta) == sign_offer_token(SECRETO, oferta)


def test_alterado_o_con_otro_secreto() -> None:
    token = sign_offer_token(SECRETO, uuid.uuid4())
    alterado = token[:-2] + ("A" if token[-2] != "A" else "B") + token[-1]

    assert verify_offer_token(SECRETO, alterado) is None
    assert verify_offer_token("otro-secreto-de-prueba-32-bytes-xx", token) is None


def test_forma_canonica() -> None:
    token = sign_offer_token(SECRETO, uuid.uuid4())
    variantes = {token[:-1] + c for c in "AEIMQUYcgkosw048"} - {token}

    assert all(verify_offer_token(SECRETO, v) is None for v in variantes)


def test_contextos_separados_de_la_gestion() -> None:
    ident = uuid.uuid4()
    gestion = sign_manage_token(SECRETO, ident)
    oferta = sign_offer_token(SECRETO, ident)

    assert verify_offer_token(SECRETO, gestion) is None
    assert verify_manage_token(SECRETO, oferta) is None
    # Mismo cuerpo con el prefijo cambiado: la firma de contexto no coincide.
    assert verify_offer_token(SECRETO, "w1." + gestion[3:]) is None


@pytest.mark.parametrize("basura", ["", "w1.", "v1.abc", "w1." + "a" * 43 + "!", "x" * 200])
def test_basura(basura: str) -> None:
    assert verify_offer_token(SECRETO, basura) is None


def test_sin_secreto() -> None:
    with pytest.raises(ManageLinkDisabled):
        sign_offer_token("", uuid.uuid4())
    assert verify_offer_token("", "w1." + "a" * 43) is None
