"""Enums del dominio (mapeados a tipos enum nativos de Postgres)."""

import enum


class UserRole(enum.StrEnum):
    """Roles del personal de la clínica (conjunto cerrado). El paciente no es usuario."""

    ADMIN = "admin"
    RECEPCION = "recepcion"
    ODONTOLOGO = "odontologo"


class AuthEventType(enum.StrEnum):
    """Eventos de seguridad auditables (tabla append-only `auth_event`, C-03)."""

    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    REFRESH_REUSE_DETECTED = "refresh_reuse_detected"
    LOGOUT = "logout"
    PASSWORD_CHANGED = "password_changed"
    USER_CREATED = "user_created"
    USER_UPDATED = "user_updated"
    USER_DEACTIVATED = "user_deactivated"
    ROLE_CHANGED = "role_changed"
