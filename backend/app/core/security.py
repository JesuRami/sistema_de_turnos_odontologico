"""Seguridad JWT (stub C-01; implementación completa en C-03).

Contrato futuro (regla dura 10): access ≤15 min, refresh rotativo con
reuse-detection (blacklist en Redis), cookie HttpOnly Secure SameSite=Lax,
pin de alg, validación iss/aud/exp.
"""

from datetime import UTC, datetime, timedelta

from jose import jwt

ALGORITHM_PIN = "HS256"


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
