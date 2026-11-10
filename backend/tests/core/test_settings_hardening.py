"""Configuración del borde endurecido (C-14, D1/D4/D5/D7): defaults y arranque en prod."""

from __future__ import annotations

from typing import Any

import pytest
from app.core.database import server_settings
from app.core.settings import Settings, SettingsError

BASE: dict[str, Any] = {
    "DATABASE_URL": "postgresql+asyncpg://turnos:clave@localhost:5432/turnos_test",
    "REDIS_URL": "redis://localhost:6379/0",
    "JWT_SECRET": "s" * 32,
}
PROD_OK: dict[str, Any] = {
    "ENV": "prod",
    "MANAGE_LINK_SECRET": "l" * 32,
    "ALLOWED_HOSTS": "turnos.example.com,*.turnos.example.com",
    "CORS_ORIGINS": "https://turnos.example.com",
    "FRONTEND_PUBLIC_URL": "https://turnos.example.com",
}


def _settings(**overrides: object) -> Settings:
    return Settings.model_validate({**BASE, **overrides})


def test_defaults_del_contrato() -> None:
    s = _settings()

    assert s.BOOKING_RATE_LIMIT == "300/minute"
    assert s.GLOBAL_RATE_LIMIT_BACKEND == "memory"
    assert (s.DB_STATEMENT_TIMEOUT_MS, s.DB_LOCK_TIMEOUT_MS, s.DB_IDLE_TX_TIMEOUT_MS) == (
        15_000,
        3_000,
        60_000,
    )
    assert s.WEBHOOK_INVALID_SIGNATURE_RATE_LIMIT == "20/60s"
    assert s.APP_DB_USER == "turnos_app"
    assert s.allowed_hosts == ["*"]
    # HSTS solo en prod.
    assert s.hsts_seconds == 0


def test_prod_valido_arranca_y_activa_hsts() -> None:
    s = _settings(**PROD_OK)
    assert s.hsts_seconds == 31_536_000
    assert s.allowed_hosts == ["turnos.example.com", "*.turnos.example.com"]


@pytest.mark.parametrize(
    ("campo", "valor", "nombra"),
    [
        ("ALLOWED_HOSTS", "*", "ALLOWED_HOSTS"),
        ("ALLOWED_HOSTS", "", "ALLOWED_HOSTS"),
        ("CORS_ORIGINS", "*", "CORS_ORIGINS"),
        ("CORS_ORIGINS", "http://turnos.example.com", "CORS_ORIGINS"),
        ("CORS_ORIGINS", "", "CORS_ORIGINS"),
        ("FRONTEND_PUBLIC_URL", "http://turnos.example.com", "FRONTEND_PUBLIC_URL"),
    ],
)
def test_prod_rechaza_comodines_y_origenes_en_claro(campo: str, valor: str, nombra: str) -> None:
    with pytest.raises(SettingsError) as exc_info:
        _settings(**{**PROD_OK, campo: valor})
    assert nombra in str(exc_info.value)


def test_dev_admite_comodin_de_hosts() -> None:
    assert _settings(ALLOWED_HOSTS="*").allowed_hosts == ["*"]


@pytest.mark.parametrize("usuario", ["Turnos", "a", "app;drop", "turnos app", "x" * 70])
def test_app_db_user_invalido_aborta_el_arranque(usuario: str) -> None:
    with pytest.raises(SettingsError) as exc_info:
        _settings(APP_DB_USER=usuario)
    assert "APP_DB_USER" in str(exc_info.value)


def test_cupo_de_firmas_invalidas_con_formato_validado() -> None:
    with pytest.raises(ValueError):
        _settings(WEBHOOK_INVALID_SIGNATURE_RATE_LIMIT="muchos")


def test_server_settings_de_las_conexiones() -> None:
    s = _settings(DB_STATEMENT_TIMEOUT_MS=1000, DB_LOCK_TIMEOUT_MS=0)
    valores = server_settings(s, "turnos-worker")

    assert valores == {
        "application_name": "turnos-worker",
        "statement_timeout": "1000",
        "idle_in_transaction_session_timeout": "60000",
    }
    assert server_settings(None, "turnos-api") == {"application_name": "turnos-api"}
