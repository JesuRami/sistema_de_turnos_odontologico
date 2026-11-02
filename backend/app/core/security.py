"""Seguridad: hashing de contraseñas argon2id (C-02) y JWT (stub C-01; completo en C-03).

Contrato futuro (regla dura 10): access ≤15 min, refresh rotativo con
reuse-detection (blacklist en Redis), cookie HttpOnly Secure SameSite=Lax,
pin de alg, validación iss/aud/exp.
"""

from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError
from jose import jwt

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


def create_access_token(sub: str, secret: str, minutes: int = 15) -> str:
    """Crea un access token corto (stub funcional para C-01)."""
    now = datetime.now(UTC)
    payload = {
        "sub": sub,
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
    }
    return str(jwt.encode(payload, secret, algorithm=ALGORITHM_PIN))


def decode_token(token: str, secret: str) -> dict[str, object]:
    """Decodifica y valida un token con alg pineado (rechaza alg:none)."""
    return jwt.decode(token, secret, algorithms=[ALGORITHM_PIN])  # type: ignore[no-any-return]
