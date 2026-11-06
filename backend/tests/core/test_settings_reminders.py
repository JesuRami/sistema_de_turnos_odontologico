"""Settings del motor de recordatorios (C-09, D10/D13): defaults, formato y `.env.example`."""

from pathlib import Path

import pytest
from app.core.settings import Settings, SettingsError
from pydantic import ValidationError

BASE = {
    "DATABASE_URL": "postgresql+asyncpg://turnos:clave@localhost:5432/turnos_test",
    "REDIS_URL": "redis://localhost:6379/0",
    "JWT_SECRET": "s" * 32,
}
NUEVAS = (
    "MANAGE_LINK_SECRET",
    "REMINDER_WHATSAPP_PROVIDER",
    "REMINDER_EMAIL_PROVIDER",
    "REMINDER_MAX_ATTEMPTS",
    "REMINDER_BACKOFF_MINUTES",
    "REMINDER_LEASE_MINUTES",
    "REMINDER_TICK_BUDGET_S",
    "REMINDER_BATCH_SIZE",
    "REMINDER_COST_WHATSAPP_MICROS",
    "REMINDER_COST_EMAIL_MICROS",
)
ENV_EXAMPLE = Path(__file__).resolve().parents[3] / ".env.example"


def _settings(**overrides: object) -> Settings:
    return Settings.model_validate({**BASE, **overrides})


def test_defaults_del_contrato_de_d13() -> None:
    settings = _settings()

    assert settings.REMINDER_WHATSAPP_PROVIDER == "disabled"
    assert settings.REMINDER_EMAIL_PROVIDER == "disabled"
    assert settings.REMINDER_MAX_ATTEMPTS == 3
    assert settings.reminder_backoff_minutes == (5, 30, 120)
    assert settings.REMINDER_LEASE_MINUTES == 5
    assert settings.REMINDER_TICK_BUDGET_S == 50
    assert settings.REMINDER_BATCH_SIZE == 100
    assert settings.REMINDER_COST_WHATSAPP_MICROS == 0
    assert settings.REMINDER_COST_EMAIL_MICROS == 0


def test_en_dev_el_secreto_de_links_puede_faltar_y_deshabilita_los_firmados() -> None:
    settings = _settings(ENV="dev")

    assert settings.MANAGE_LINK_SECRET.get_secret_value() == ""


def test_fuera_de_dev_el_secreto_de_links_es_obligatorio() -> None:
    with pytest.raises(SettingsError) as exc_info:
        _settings(ENV="prod")

    assert "MANAGE_LINK_SECRET" in str(exc_info.value)


@pytest.mark.parametrize("entorno", ["dev", "prod"])
def test_secreto_de_links_corto_falla_sin_imprimir_el_valor(entorno: str) -> None:
    corto = "corto-no-debe-aparecer"
    with pytest.raises(SettingsError) as exc_info:
        _settings(ENV=entorno, MANAGE_LINK_SECRET=corto)

    assert "MANAGE_LINK_SECRET" in str(exc_info.value)
    assert corto not in str(exc_info.value)


def test_secreto_de_links_valido_se_acepta() -> None:
    settings = _settings(ENV="prod", MANAGE_LINK_SECRET="l" * 32)

    assert settings.MANAGE_LINK_SECRET.get_secret_value() == "l" * 32


@pytest.mark.parametrize(
    ("nombre", "valor"),
    [
        ("REMINDER_WHATSAPP_PROVIDER", "smtp"),
        ("REMINDER_WHATSAPP_PROVIDER", "twilio"),  # `meta` entra con C-10
        ("REMINDER_EMAIL_PROVIDER", "sendgrid"),
    ],
)
def test_proveedor_fuera_del_catalogo_falla(nombre: str, valor: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        _settings(**{nombre: valor})

    assert nombre in str(exc_info.value)


@pytest.mark.parametrize(
    ("nombre", "valor"),
    [
        ("REMINDER_WHATSAPP_PROVIDER", "fake"),
        ("REMINDER_EMAIL_PROVIDER", "smtp"),
        ("REMINDER_EMAIL_PROVIDER", "fake"),
    ],
)
def test_proveedor_del_catalogo_se_acepta(nombre: str, valor: str) -> None:
    assert getattr(_settings(**{nombre: valor}), nombre) == valor


@pytest.mark.parametrize("valor", ["", "abc", "5,,30", "5,-1", "0,30", "5;30"])
def test_backoff_invalido_falla(valor: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        _settings(REMINDER_BACKOFF_MINUTES=valor)

    assert "REMINDER_BACKOFF_MINUTES" in str(exc_info.value)


def test_backoff_debe_cubrir_los_reintentos() -> None:
    with pytest.raises(SettingsError) as exc_info:
        _settings(REMINDER_MAX_ATTEMPTS=4, REMINDER_BACKOFF_MINUTES="5,30")

    assert "REMINDER_BACKOFF_MINUTES" in str(exc_info.value)


@pytest.mark.parametrize(
    "nombre",
    [
        "REMINDER_MAX_ATTEMPTS",
        "REMINDER_LEASE_MINUTES",
        "REMINDER_TICK_BUDGET_S",
        "REMINDER_BATCH_SIZE",
        "REMINDER_WORKER_CONCURRENCY",
    ],
)
@pytest.mark.parametrize("valor", [0, -1])
def test_enteros_positivos(nombre: str, valor: int) -> None:
    with pytest.raises(ValidationError) as exc_info:
        _settings(**{nombre: valor})

    assert nombre in str(exc_info.value)


@pytest.mark.parametrize("nombre", ["REMINDER_COST_WHATSAPP_MICROS", "REMINDER_COST_EMAIL_MICROS"])
def test_costo_no_puede_ser_negativo(nombre: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        _settings(**{nombre: -1})

    assert nombre in str(exc_info.value)


def test_env_example_contiene_todas_las_claves_nuevas() -> None:
    claves = {
        linea.partition("=")[0].strip()
        for linea in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if linea.strip() and not linea.strip().startswith("#") and "=" in linea
    }

    faltan = [n for n in NUEVAS if n not in claves]
    assert faltan == []


def test_env_example_instancia_settings_validos() -> None:
    pares = {}
    for linea in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        if linea.strip() and not linea.strip().startswith("#") and "=" in linea:
            clave, _, valor = linea.partition("=")
            pares[clave.strip()] = valor.strip()
    nuevas = {n: pares[n] for n in NUEVAS if n in pares}

    settings = _settings(**nuevas)

    assert len(settings.MANAGE_LINK_SECRET.get_secret_value().encode()) >= 32
