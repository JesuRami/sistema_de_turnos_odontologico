"""Seguridad: hashing de contraseñas argon2id (C-02).

El contrato JWT completo vive en `app.core.jwt` desde C-03 (firma, claims,
`iss`/`aud`/`exp` y `sid`); este módulo conserva solo el hasher y el pin de
algoritmo que ambos comparten.
"""

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

ALGORITHM_PIN = "HS256"

# Parámetros argon2id RFC 9106 "low memory" (64 MiB, t=3, p=4); se ajustan por deploy en C-14.
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, type=Type.ID)


def hash_password(password: str) -> str:
    """Hash argon2id con sal aleatoria; el valor en claro nunca se persiste ni se loguea."""
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """True si `password` corresponde a `hashed`; falso (sin excepción) ante hash inválido."""
    try:
        return _hasher.verify(hashed, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(hashed: str) -> bool:
    """True si el hash usa parámetros distintos a los actuales (C-03 rehashea en login)."""
    return _hasher.check_needs_rehash(hashed)
