"""Fixtures globales de tests (sin DB real en C-01 salvo Alembic en CI)."""

import os

import pytest

# Entorno mínimo para que Settings() falle-rápido pase en tests.
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "test-secret-no-produccion")


@pytest.fixture()
def anyio_backend() -> str:
    """Backend para tests async."""
    return "asyncio"
