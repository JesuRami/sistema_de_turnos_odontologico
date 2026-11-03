"""Contrato del access token C-03: claims, algoritmo pineado y validaciones."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.core.jwt import (
    AccessClaims,
    TokenExpiredError,
    TokenInvalidError,
    decode_access_token,
    encode_access_token,
)
from app.core.security import ALGORITHM_PIN
from app.core.settings import Settings
from app.models import UserRole
from jose import jwt
from pydantic import SecretStr

USER_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
CLINIC_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
SID = "sid-de-prueba"


def _emitir(settings: Settings, clock: object, **overrides: object) -> tuple[str, int]:
    valores: dict[str, object] = {
        "user_id": USER_ID,
        "clinic_id": CLINIC_ID,
        "roles": [UserRole.ADMIN],
        "email": "admin@example.com",
        "sid": SID,
        "settings": settings,
        "clock": clock,
    }
    valores.update(overrides)
    return encode_access_token(**valores)  # type: ignore[arg-type]


def _claims(token: str) -> dict[str, object]:
    return jwt.get_unverified_claims(token)  # type: ignore[no-any-return]


def test_emite_el_contrato_completo_y_vigencia_maxima(settings: Settings, clock: object) -> None:
    """WHEN se emite un access THEN trae los diez claims y `exp - iat <= 900`."""
    token, expires_in = _emitir(settings, clock)
    claims = _claims(token)

    assert set(claims) >= {
        "sub",
        "clinic_id",
        "roles",
        "email",
        "jti",
        "sid",
        "type",
        "iat",
        "exp",
        "iss",
        "aud",
    }
    assert claims["sub"] == str(USER_ID)
    assert claims["clinic_id"] == str(CLINIC_ID)
    assert claims["roles"] == ["admin"]
    assert claims["type"] == "access"
    assert claims["iss"] == settings.JWT_ISSUER
    assert claims["aud"] == settings.JWT_AUDIENCE
    assert int(claims["exp"]) - int(claims["iat"]) <= 900  # type: ignore[call-overload]
    assert expires_in <= 900


def test_decode_acepta_el_token_propio(settings: Settings, clock: object) -> None:
    """WHEN se decodifica el token emitido THEN devuelve los datos tipados."""
    token, _ = _emitir(settings, clock)

    claims = decode_access_token(token, settings)

    assert isinstance(claims, AccessClaims)
    assert claims.user_id == USER_ID
    assert claims.clinic_id == CLINIC_ID
    assert claims.roles == (UserRole.ADMIN,)
    assert claims.sid == SID
    assert claims.email == "admin@example.com"


def test_rechaza_exp_vencido(settings: Settings, clock: object) -> None:
    """WHEN el `exp` ya pasó THEN TokenExpiredError (código token_expired)."""
    vencido = lambda: datetime.now(UTC) - timedelta(hours=1)  # noqa: E731
    token, _ = _emitir(settings, vencido)

    with pytest.raises(TokenExpiredError):
        decode_access_token(token, settings)
    assert TokenExpiredError.code == "token_expired"


def test_rechaza_firma_con_otro_secreto(settings: Settings, clock: object) -> None:
    """WHEN la firma no corresponde al secreto THEN TokenInvalidError genérico."""
    token, _ = _emitir(settings, clock)
    otro = settings.model_copy(update={"JWT_SECRET": SecretStr("z" * 32)})

    with pytest.raises(TokenInvalidError):
        decode_access_token(token, otro)


def _unsigned(payload: dict[str, object]) -> str:
    """Token `alg=none` armado a mano (python-jose se niega a firmarlo)."""
    import base64
    import json

    def _b64(data: dict[str, object]) -> str:
        crudo = json.dumps(data, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(crudo).rstrip(b"=").decode()

    return f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(payload)}."


def test_rechaza_alg_none(settings: Settings) -> None:
    """WHEN el token no tiene firma (alg=none) THEN se rechaza sin ejecutar endpoint."""
    sin_firma = _unsigned({"sub": str(USER_ID), "type": "access", "sid": SID})

    with pytest.raises(TokenInvalidError):
        decode_access_token(sin_firma, settings)


def test_rechaza_algoritmo_distinto_al_pineado(settings: Settings) -> None:
    """WHEN el token usa HS512 THEN se rechaza (algoritmo fijado en servidor)."""
    firmado = jwt.encode(
        {"sub": str(USER_ID), "type": "access", "sid": SID},
        settings.JWT_SECRET.get_secret_value(),
        algorithm="HS512",
    )

    with pytest.raises(TokenInvalidError):
        decode_access_token(firmado, settings)


def _forjar(settings: Settings, **overrides: object) -> str:
    ahora = datetime.now(UTC)
    payload: dict[str, object] = {
        "sub": str(USER_ID),
        "clinic_id": str(CLINIC_ID),
        "roles": ["admin"],
        "email": "admin@example.com",
        "jti": str(uuid.uuid4()),
        "sid": SID,
        "type": "access",
        "iat": ahora,
        "exp": ahora + timedelta(minutes=15),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
    }
    payload.update(overrides)
    return str(jwt.encode(payload, settings.JWT_SECRET.get_secret_value(), algorithm=ALGORITHM_PIN))


@pytest.mark.parametrize(
    "override",
    [
        {"iss": "otro-emisor"},
        {"aud": "otra-audiencia"},
        {"type": "refresh"},
        {"sid": None},
        {"clinic_id": None},
        {"roles": ["superadmin"]},
    ],
)
def test_rechaza_claims_invalidos(settings: Settings, override: dict[str, object]) -> None:
    """WHEN `iss`/`aud`/`type`/`sid`/`clinic_id`/`roles` no cuadran THEN 401 genérico."""
    token = _forjar(settings, **override)

    with pytest.raises(TokenInvalidError):
        decode_access_token(token, settings)
