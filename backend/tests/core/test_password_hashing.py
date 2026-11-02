"""Hashing de contraseñas argon2id: no reversible, verificable y tolerante a basura."""

import pytest
from app.core.security import hash_password, needs_rehash, verify_password

CLAVE = "clave-de-prueba-no-real-1"


def test_hash_es_argon2id_y_no_contiene_la_clave() -> None:
    hashed = hash_password(CLAVE)
    assert hashed.startswith("$argon2id$")
    assert CLAVE not in hashed
    assert verify_password(CLAVE, hashed) is True


@pytest.mark.parametrize(
    "hashed",
    ["", "no-es-un-hash", "$argon2id$v=19$m=1,t=1,p=1$corrupto$corrupto", "$2b$12$abcdefghijk"],
)
def test_hash_malformado_verifica_falso_sin_excepcion(hashed: str) -> None:
    assert verify_password(CLAVE, hashed) is False


def test_otra_clave_no_verifica() -> None:
    hashed = hash_password(CLAVE)
    assert verify_password("otra-clave-de-prueba", hashed) is False
    assert verify_password("", hashed) is False


def test_misma_clave_da_hashes_distintos_y_ambos_verifican() -> None:
    h1, h2 = hash_password(CLAVE), hash_password(CLAVE)
    assert h1 != h2
    assert verify_password(CLAVE, h1) is True
    assert verify_password(CLAVE, h2) is True


def test_needs_rehash_detecta_parametros_viejos_y_hash_actual() -> None:
    from argon2 import PasswordHasher

    viejo = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(CLAVE)
    assert needs_rehash(viejo) is True
    assert needs_rehash(hash_password(CLAVE)) is False


def test_hash_codifica_los_parametros_rfc_9106_low_memory() -> None:
    from argon2 import extract_parameters
    from argon2.profiles import RFC_9106_LOW_MEMORY

    params = extract_parameters(hash_password(CLAVE))
    assert (params.time_cost, params.memory_cost, params.parallelism) == (
        RFC_9106_LOW_MEMORY.time_cost,
        RFC_9106_LOW_MEMORY.memory_cost,
        RFC_9106_LOW_MEMORY.parallelism,
    )
