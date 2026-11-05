"""Settings de la gestión por token (C-08, D10/D13): defaults, formato y `.env.example`."""

from pathlib import Path

import pytest
from app.core.settings import Settings
from pydantic import ValidationError

BASE = {
    "DATABASE_URL": "postgresql+asyncpg://turnos:clave@localhost:5432/turnos_test",
    "REDIS_URL": "redis://localhost:6379/0",
    "JWT_SECRET": "s" * 32,
}
RATE_LIMITS = (
    "MANAGE_READ_IP_RATE_LIMIT",
    "MANAGE_READ_TOKEN_RATE_LIMIT",
    "MANAGE_WRITE_IP_RATE_LIMIT",
    "MANAGE_WRITE_TOKEN_RATE_LIMIT",
)
NUEVAS = (*RATE_LIMITS, "MANAGE_TOKEN_TTL_H")
ENV_EXAMPLE = Path(__file__).resolve().parents[3] / ".env.example"


def _settings(**overrides: object) -> Settings:
    return Settings.model_validate({**BASE, **overrides})


def test_defaults_del_contrato_de_d10() -> None:
    settings = _settings()

    assert settings.MANAGE_READ_IP_RATE_LIMIT == "120/60s"
    assert settings.MANAGE_READ_TOKEN_RATE_LIMIT == "60/60s"
    assert settings.MANAGE_WRITE_IP_RATE_LIMIT == "30/60s"
    assert settings.MANAGE_WRITE_TOKEN_RATE_LIMIT == "10/60s"
    assert settings.MANAGE_TOKEN_TTL_H == 72


@pytest.mark.parametrize("nombre", RATE_LIMITS)
@pytest.mark.parametrize("valor", ["10/60", "0/60s", "abc", ""])
def test_rate_limit_invalido_falla_al_arrancar_con_mensaje_de_formato(
    nombre: str, valor: str
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        _settings(**{nombre: valor})

    assert nombre in str(exc_info.value)


@pytest.mark.parametrize("nombre", RATE_LIMITS)
def test_rate_limit_valido_se_acepta(nombre: str) -> None:
    assert getattr(_settings(**{nombre: "7/120s"}), nombre) == "7/120s"


@pytest.mark.parametrize("horas", [0, -1])
def test_ttl_del_token_debe_ser_positivo(horas: int) -> None:
    with pytest.raises(ValidationError) as exc_info:
        _settings(MANAGE_TOKEN_TTL_H=horas)

    assert "MANAGE_TOKEN_TTL_H" in str(exc_info.value)


def test_env_example_contiene_todas_las_claves_nuevas() -> None:
    claves = {
        linea.partition("=")[0].strip()
        for linea in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if linea.strip() and not linea.strip().startswith("#") and "=" in linea
    }

    faltan = [n for n in NUEVAS if n not in claves]
    assert faltan == []
