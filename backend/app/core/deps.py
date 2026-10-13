"""Dependencias FastAPI compartidas (RBAC completo en C-03)."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import Settings, get_settings


async def get_db() -> AsyncIterator[AsyncSession]:
    """Sesión async por request (engine real se cablea en C-02)."""
    raise NotImplementedError("DB session wiring llega en C-02")


def require_roles(*roles: str) -> object:
    """Fábrica de dependencias RBAC (stub C-01; enforcement en C-03)."""

    async def _checker(settings: Annotated[Settings, Depends(get_settings)]) -> None:
        _ = (roles, settings)
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="RBAC se implementa en C-03",
        )

    return _checker
