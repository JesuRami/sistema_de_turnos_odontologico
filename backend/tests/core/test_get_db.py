"""`get_db` real: sesión async usable por request y cerrada al terminar."""

from typing import Any, cast

import pytest
from app.core.deps import get_db
from app.models import Clinic
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request

pytestmark = pytest.mark.integration


async def test_get_db_entrega_sesion_usable_y_la_cierra(db_session: AsyncSession) -> None:
    """WHEN un endpoint usa `get_db` THEN puede insertar/leer y la sesión se cierra al final."""
    maker: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=db_session.bind, expire_on_commit=False
    )
    app = FastAPI()
    app.state.sessionmaker = maker
    request = Request({"type": "http", "app": app, "headers": [], "method": "GET", "path": "/"})

    generador = get_db(request)
    session = await anext(generador)
    try:
        clinic = Clinic(name="Clínica Ficticia Probe", slug="clinica-probe-get-db")
        session.add(clinic)
        await session.commit()

        encontrada = await session.scalar(select(Clinic).where(Clinic.slug == clinic.slug))
        assert encontrada is not None
    finally:
        await cast(Any, generador).aclose()

    # `close()` expulsa el identity map y libera la conexión (`is_active` sigue True en 2.0).
    assert len(session.identity_map) == 0
    assert session.in_transaction() is False
