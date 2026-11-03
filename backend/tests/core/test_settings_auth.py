"""Settings de auth: secreto JWT validado al arrancar y defaults del contrato C-03."""

import pytest
from app.core.settings import Settings, SettingsError
from pydantic import ValidationError

SECRETO_32 = "s" * 32
BASE = {
    "DATABASE_URL": "postgresql+asyncpg://turnos:clave@localhost:5432/turnos_test",
    "REDIS_URL": "redis://localhost:6379/0",
    "JWT_SECRET": SECRETO_32,
}


def _settings(**overrides: object) -> Settings:
    """Construye Settings desde un dict explícito (no lee `.env` ni el entorno)."""
    return Settings.model_validate({**BASE, **overrides})


def test_secreto_de_20_bytes_aborta_nombrando_la_variable_sin_imprimirla() -> None:
    """WHEN JWT_SECRET mide 20 bytes THEN el arranque falla nombrando JWT_SECRET, nunca su valor."""
    secreto_corto = "corto-inseguro-12345"  # 20 bytes
    assert len(secreto_corto.encode()) == 20

    with pytest.raises(SettingsError) as exc_info:
        _settings(JWT_SECRET=secreto_corto)

    mensaje = str(exc_info.value)
    assert "JWT_SECRET" in mensaje
    assert "32" in mensaje
    assert secreto_corto not in mensaje


def test_secreto_de_32_bytes_arranca() -> None:
    """WHEN JWT_SECRET tiene 32+ bytes THEN Settings construye sin error."""
    assert _settings().JWT_SECRET.get_secret_value() == SECRETO_32
    assert _settings(JWT_SECRET="s" * 33).JWT_SECRET.get_secret_value() == "s" * 33


def test_algoritmo_distinto_de_hs256_se_rechaza() -> None:
    """WHEN JWT_ALGORITHM no es HS256 THEN el arranque falla (alg pineado, sin degradar)."""
    with pytest.raises(SettingsError) as exc_info:
        _settings(JWT_ALGORITHM="HS512")

    mensaje = str(exc_info.value)
    assert "JWT_ALGORITHM" in mensaje
    assert "HS256" in mensaje


def test_access_tokens_no_superan_15_minutos() -> None:
    """WHEN JWT_ACCESS_MINUTES > 15 THEN el arranque falla (regla dura 10)."""
    with pytest.raises(SettingsError) as exc_info:
        _settings(JWT_ACCESS_MINUTES=60)

    assert "JWT_ACCESS_MINUTES" in str(exc_info.value)


def test_defaults_nuevos_del_change() -> None:
    """WHEN no se configuran THEN existen los defaults de sesión, rate-limit y cookie."""
    settings = _settings()

    assert settings.JWT_REFRESH_DAYS == 7
    assert settings.AUTH_LOGIN_RATE_LIMIT == "5/60s"
    assert settings.AUTH_LOGIN_IP_RATE_LIMIT == "30/60s"
    assert settings.AUTH_REFRESH_RATE_LIMIT == "60/60s"
    assert settings.AUTH_PASSWORD_RATE_LIMIT == "5/60s"
    assert settings.COOKIE_DOMAIN == ""
    assert settings.REDIS_AUTH_DB == 15


@pytest.mark.parametrize("valor", ["cinco/60s", "5/60", "5/minuto", ""])
def test_rate_limit_de_auth_con_formato_invalido_aborta(valor: str) -> None:
    """WHEN un límite de auth no cumple `<n>/<segundos>s` THEN el arranque falla."""
    with pytest.raises(ValidationError) as exc_info:
        _settings(AUTH_LOGIN_RATE_LIMIT=valor)

    assert "AUTH_LOGIN_RATE_LIMIT" in str(exc_info.value)
