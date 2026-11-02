"""Enums del dominio (mapeados a tipos enum nativos de Postgres)."""

import enum


class UserRole(enum.StrEnum):
    """Roles del personal de la clínica (conjunto cerrado). El paciente no es usuario."""

    ADMIN = "admin"
    RECEPCION = "recepcion"
    ODONTOLOGO = "odontologo"
