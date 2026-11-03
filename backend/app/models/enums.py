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


class BlockReason(enum.StrEnum):
    """Catálogo cerrado de motivos de bloqueo de agenda (KB 04 §block, C-04)."""

    VACACIONES = "vacaciones"
    FERIADO = "feriado"
    MANTENIMIENTO = "mantenimiento"
    REUNION = "reunion"
    OTRO = "otro"


class ConfigEntity(enum.StrEnum):
    """Entidad de configuración auditada en `agenda_config_event` (C-04)."""

    PROFESSIONAL = "professional"
    CHAIR = "chair"
    SCHEDULE_RULE = "schedule_rule"
    BLOCK = "block"
    CLINIC_POLICY = "clinic_policy"


class ConfigAction(enum.StrEnum):
    """Acción auditada sobre la configuración de agenda (C-04)."""

    CREATED = "created"
    UPDATED = "updated"
    DEACTIVATED = "deactivated"
    REACTIVATED = "reactivated"
    REMOVED = "removed"
