"""Paginación por cursor (regla dura 8: nunca OFFSET grande en agenda/reportes)."""

import base64
import binascii
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import InstrumentedAttribute

from app.common.exceptions import DomainError


class CursorPage(BaseModel):
    """Parámetros de paginación por cursor."""

    model_config = ConfigDict(extra="forbid")

    cursor: str | None = Field(default=None)
    limit: int = Field(default=50, ge=1, le=200)


def encode_cursor(ts: datetime, row_id: uuid.UUID) -> str:
    """Cursor opaco `timestamp|id` en base64url (orden estable sin OFFSET)."""
    crudo = f"{ts.isoformat()}|{row_id}".encode()
    return base64.urlsafe_b64encode(crudo).decode()


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """Decodifica el cursor; formato inválido → `422 invalid_cursor`."""
    try:
        crudo = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts, _, row_id = crudo.partition("|")
        return datetime.fromisoformat(ts), uuid.UUID(row_id)
    except (ValueError, binascii.Error, UnicodeDecodeError):
        raise DomainError(422, "invalid_cursor") from None


async def paginate_entities(
    session: AsyncSession,
    stmt: Select[Any],
    ts_col: InstrumentedAttribute[datetime],
    id_col: InstrumentedAttribute[uuid.UUID],
    cursor: str | None,
    limit: int,
) -> tuple[Sequence[Any], str | None]:
    """Página de entidades ordenadas por `(ts_col, id_col)` y el cursor siguiente."""
    if cursor:
        ts, ultimo_id = decode_cursor(cursor)
        stmt = stmt.where(or_(ts_col > ts, and_(ts_col == ts, id_col > ultimo_id)))
    filas = (await session.execute(stmt.order_by(ts_col, id_col).limit(limit + 1))).scalars().all()
    if len(filas) <= limit:
        return filas, None
    ultima = filas[limit - 1]
    return filas[:limit], encode_cursor(getattr(ultima, ts_col.key), getattr(ultima, id_col.key))
