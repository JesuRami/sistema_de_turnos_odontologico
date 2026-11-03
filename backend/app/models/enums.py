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


class AppointmentStatus(enum.StrEnum):
    """Estado del turno (RN-ST-01, C-05). Vigentes: pending, confirmed, present."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    PRESENT = "present"
    ABSENT = "absent"
    NO_SHOW = "no_show"
    CANCELLED = "cancelled"


class AppointmentOrigin(enum.StrEnum):
    """Canal por el que nació el turno (RN-ST-02, C-05)."""

    RECEPTION = "reception"
    ONLINE = "online"


class CancellationReason(enum.StrEnum):
    """Catálogo cerrado de motivos de cancelación (RN-CX-04, C-05)."""

    PACIENTE = "paciente"
    PROFESIONAL = "profesional"
    CLINICA = "clinica"
    BLOQUEO = "bloqueo"
    OTRO = "otro"


class AppointmentEventType(enum.StrEnum):
    """Mutación auditada de un turno en `appointment_event` (C-05)."""

    CREATED = "created"
    OVERBOOKING_CREATED = "overbooking_created"
    CONFIRMED = "confirmed"
    RESCHEDULED = "rescheduled"
    CANCELLED = "cancelled"
    PRESENT = "present"
    ABSENT = "absent"
    NO_SHOW = "no_show"
    UPDATED = "updated"


class ActorType(enum.StrEnum):
    """Quién originó una mutación de turno (C-05; `patient_token` llega con C-08)."""

    USER = "user"
    PATIENT_TOKEN = "patient_token"
    SYSTEM = "system"


# Vigente = ocupa agenda (RN-AG-01); `absent`, `no_show` y `cancelled` liberan el hueco.
VIGENT_STATUSES = (
    AppointmentStatus.PENDING,
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.PRESENT,
)
