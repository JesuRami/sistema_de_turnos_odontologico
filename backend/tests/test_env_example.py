"""Contrato `.env.example` ⊆ claves requeridas de `Settings` (sin secretos reales)."""

from pathlib import Path

from app.core.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
REQUIRED = ("DATABASE_URL", "REDIS_URL", "JWT_SECRET")


def _example_keys() -> dict[str, str]:
    example = REPO_ROOT / ".env.example"
    assert example.exists(), ".env.example no existe en la raíz del repo"
    pairs: dict[str, str] = {}
    for line in example.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        pairs[key.strip()] = value.strip()
    return pairs


def test_claves_requeridas_presentes_en_ejemplo() -> None:
    """Toda clave requerida de Settings existe en .env.example."""
    keys = _example_keys()
    for required in REQUIRED:
        assert required in keys, f"{required} falta en .env.example"
    # Contrato completo del spec (WHEN se inspecciona .env.example THEN contiene…).
    for expected in (
        "JWT_ACCESS_MINUTES",
        "WHATSAPP_TOKEN",
        "CLINIC_TZ_DEFAULT",
        "BOOKING_RATE_LIMIT",
        "MANAGE_TOKEN_TTL_H",
        "FRONTEND_PUBLIC_URL",
        "CORS_ORIGINS",
    ):
        assert expected in keys, f"{expected} falta en .env.example"
    assert any(k.startswith("META_") for k in keys), "faltan claves META_*"
    assert any(k.startswith("EMAIL_") for k in keys), "faltan claves EMAIL_*"


def test_ejemplo_sin_secretos_reales() -> None:
    """Los valores de ejemplo son placeholders, nunca secretos reales."""
    forbidden_fragments = ("prod-secret", "real-token", "sk-live")
    content = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    for fragment in forbidden_fragments:
        assert fragment not in content


def test_settings_falla_rapido_sin_requeridas() -> None:
    """WHEN falta JWT_SECRET/DATABASE_URL THEN Settings aborta nombrando la variable."""
    import os

    import pytest
    from pydantic import ValidationError

    backup = {k: os.environ.pop(k, None) for k in REQUIRED}
    try:
        with pytest.raises(ValidationError) as exc_info:
            Settings()  # type: ignore[call-arg]
        message = str(exc_info.value)
        assert any(k in message for k in REQUIRED)
    finally:
        for key, value in backup.items():
            if value is not None:
                os.environ[key] = value
