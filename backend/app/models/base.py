"""Base SQLAlchemy 2.x async (modelos reales en C-02).

Convenciones impuestas desde C-01:
- `AsyncSession` + `DateTime(timezone=True)` en todos los modelos.
- `clinic_id` obligatorio en toda tabla operativa (regla dura 4).
"""

from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase


class Base(AsyncAttrs, DeclarativeBase):
    """Base declarativa compartida por api + worker."""

    pass
