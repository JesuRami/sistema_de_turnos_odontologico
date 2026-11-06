"""Settings del canal WhatsApp (C-10, D3): proveedor `meta`, credenciales y defaults."""

import pytest
from app.core.settings import Settings, SettingsError

BASE = {
    "DATABASE_URL": "postgresql+asyncpg://turnos:clave@localhost:5432/turnos_test",
    "REDIS_URL": "redis://localhost:6379/0",
    "JWT_SECRET": "s" * 32,
}
META_OK = {
    "REMINDER_WHATSAPP_PROVIDER": "meta",
    "WHATSAPP_TOKEN": "token-ficticio-de-acceso-0001",
    "META_APP_SECRET": "secreto-ficticio-de-app-0001",
    "META_PHONE_NUMBER_ID": "100000000000001",
    "META_VERIFY_TOKEN": "verify-ficticio-0001",
}
REQUERIDAS_META = ("WHATSAPP_TOKEN", "META_APP_SECRET", "META_PHONE_NUMBER_ID", "META_VERIFY_TOKEN")


def _settings(**overrides: object) -> Settings:
    return Settings.model_validate({**BASE, **overrides})


def test_proveedor_meta_con_credenciales_completas() -> None:
    settings = _settings(**META_OK)

    assert settings.REMINDER_WHATSAPP_PROVIDER == "meta"
    assert settings.WHATSAPP_TOKEN.get_secret_value() == META_OK["WHATSAPP_TOKEN"]
    assert settings.META_APP_SECRET.get_secret_value() == META_OK["META_APP_SECRET"]


@pytest.mark.parametrize("faltante", REQUERIDAS_META)
def test_meta_sin_alguna_credencial_falla_sin_mostrar_valores(faltante: str) -> None:
    with pytest.raises(SettingsError) as exc_info:
        _settings(**{**META_OK, faltante: ""})

    mensaje = str(exc_info.value)
    assert faltante in mensaje
    for clave, valor in META_OK.items():
        if clave != "REMINDER_WHATSAPP_PROVIDER":
            assert valor not in mensaje


def test_los_secretos_no_aparecen_en_repr() -> None:
    settings = _settings(**META_OK)

    texto = repr(settings) + str(settings)
    assert META_OK["WHATSAPP_TOKEN"] not in texto
    assert META_OK["META_APP_SECRET"] not in texto


def test_sin_meta_las_credenciales_pueden_faltar() -> None:
    settings = _settings(REMINDER_WHATSAPP_PROVIDER="disabled")

    assert settings.WHATSAPP_TOKEN.get_secret_value() == ""


def test_defaults_nuevos() -> None:
    settings = _settings()

    assert settings.META_GRAPH_BASE_URL == "https://graph.facebook.com"
    assert settings.WHATSAPP_HTTP_TIMEOUT_S == 10
    assert settings.WHATSAPP_WEBHOOK_MAX_BYTES == 1024 * 1024
    assert settings.WHATSAPP_REPLY_MAX_ATTEMPTS == 3


def test_env_example_declara_las_claves_nuevas() -> None:
    from pathlib import Path

    contenido = (Path(__file__).resolve().parents[3] / ".env.example").read_text(encoding="utf-8")
    claves = {linea.split("=", 1)[0] for linea in contenido.splitlines() if "=" in linea}
    for clave in (
        "META_GRAPH_BASE_URL",
        "WHATSAPP_HTTP_TIMEOUT_S",
        "WHATSAPP_WEBHOOK_MAX_BYTES",
        "WHATSAPP_REPLY_MAX_ATTEMPTS",
    ):
        assert clave in claves, f"{clave} falta en .env.example"
