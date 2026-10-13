"""Dependencias comunes (DB/tenant se cablean en C-02/C-03)."""

from fastapi import Header


async def get_clinic_id(x_clinic_id: str | None = Header(default=None)) -> str | None:
    """Extrae el tenant del header (enforcement real + test cross-tenant en C-02)."""
    return x_clinic_id
