"""Settings de la reserva pública (C-07, D14): defaults, validación de formato y `.env.example`."""

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
    "PUBLIC_BOOKING_IP_RATE_LIMIT",
    "PUBLIC_BOOKING_SLUG_RATE_LIMIT",
    "PUBLIC_BOOKING_READ_RATE_LIMIT",
)
NUEVAS = (*RATE_LIMITS, "PUBLIC_BOOKING_HORIZON_DAYS", "PRIVACY_POLICY_VERSION", "BOT_GUARD")
ENV_EXAMPLE = Path(__file__).resolve().parents[3] / ".env.example"


def _settings(**overrides: object) -> Settings:
    return Settings.model_validate({**BASE, **overrides})


def test_defaults_del_contrato_de_d14() -> None:
    settings = _settings()

    assert settings.PUBLIC_BOOKING_IP_RATE_LIMIT == "10/3600s"
    assert settings.PUBLIC_BOOKING_SLUG_RATE_LIMIT == "300/3600s"
    assert settings.PUBLIC_BOOKING_READ_RATE_LIMIT == "120/60s"
    assert settings.PUBLIC_BOOKING_HORIZON_DAYS == 60
    assert settings.PRIVACY_POLICY_VERSION
    assert settings.BOT_GUARD == "noop"


def test_el_rate_limit_global_en_memoria_no_se_toca() -> None:
    assert _settings().BOOKING_RATE_LIMIT == "30/minute"


@pytest.mark.parametrize("nombre", RATE_LIMITS)
@pytest.mark.parametrize("valor", ["10 por hora", "10/hora", "0/60s", "10/0s", ""])
def test_rate_limit_invalido_falla_al_arrancar_con_mensaje_de_formato(
    nombre: str, valor: str
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        _settings(**{nombre: valor})

    assert nombre in str(exc_info.value)


@pytest.mark.parametrize("nombre", RATE_LIMITS)
def test_rate_limit_valido_se_acepta(nombre: str) -> None:
    assert getattr(_settings(**{nombre: "7/120s"}), nombre) == "7/120s"


@pytest.mark.parametrize("dias", [0, -1])
def test_horizonte_debe_ser_positivo(dias: int) -> None:
    with pytest.raises(ValidationError):
        _settings(PUBLIC_BOOKING_HORIZON_DAYS=dias)


def test_env_example_contiene_todas_las_claves_nuevas() -> None:
    claves = {
        linea.partition("=")[0].strip()
        for linea in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if linea.strip() and not linea.strip().startswith("#") and "=" in linea
    }

    faltan = [n for n in NUEVAS if n not in claves]
    assert faltan == []
