"""Normalización de DATABASE_URL al driver async (asyncpg)."""

import pytest
from app.core.database import async_database_url


@pytest.mark.parametrize(
    ("raw", "esperado"),
    [
        ("postgresql://u:p@h:5432/d", "postgresql+asyncpg://u:p@h:5432/d"),
        ("postgres://u:p@h:5432/d", "postgresql+asyncpg://u:p@h:5432/d"),
        ("postgresql+asyncpg://u:p@h:5432/d", "postgresql+asyncpg://u:p@h:5432/d"),
    ],
)
def test_url_se_normaliza_a_asyncpg(raw: str, esperado: str) -> None:
    assert async_database_url(raw) == esperado


def test_driver_sincrono_no_soportado_falla_sin_filtrar_credenciales() -> None:
    with pytest.raises(ValueError) as exc:
        async_database_url("postgresql+psycopg2://u:secreto@h/d")
    assert "secreto" not in str(exc.value)
