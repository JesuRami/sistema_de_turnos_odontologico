"""Paginación por cursor descendente para listados clínicos (regla 8: sin OFFSET).

Orden `(ts DESC, id DESC)` sobre columnas explícitas; el cursor es el de `app.common.pagination`
(`timestamp|id` en base64url, `422 invalid_cursor` si no decodifica).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Select, and_, or_
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import InstrumentedAttribute

from app.common.pagination import decode_cursor, encode_cursor

MAX_LIMIT = 100
DEFAULT_LIMIT = 50


async def paginate_desc(
    session: AsyncSession,
    stmt: Select[Any],
    ts_col: InstrumentedAttribute[datetime],
    id_col: InstrumentedAttribute[uuid.UUID],
    cursor: str | None,
    limit: int,
) -> tuple[Sequence[Row[Any]], str | None]:
    """Página de filas más recientes primero y el cursor de la siguiente (o `None`)."""
    if cursor:
        ts, ultimo_id = decode_cursor(cursor)
        stmt = stmt.where(or_(ts_col < ts, and_(ts_col == ts, id_col < ultimo_id)))
    filas = (
        await session.execute(stmt.order_by(ts_col.desc(), id_col.desc()).limit(limit + 1))
    ).all()
    if len(filas) <= limit:
        return filas, None
    ultima = filas[limit - 1]
    return filas[:limit], encode_cursor(getattr(ultima, ts_col.key), getattr(ultima, id_col.key))
