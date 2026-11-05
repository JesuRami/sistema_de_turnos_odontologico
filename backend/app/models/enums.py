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
    DATA_EXPORTED = "data_exported"


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


class ReminderChannel(enum.StrEnum):
    """Canal de un recordatorio y de un consentimiento (C-09)."""

    WHATSAPP = "whatsapp"
    EMAIL = "email"


class ReminderStatus(enum.StrEnum):
    """Estado de un `reminder_job` (C-09, D1).

    `sending` es el lease del reclamo (no está en la KB); `delivered` y `read` los escribe C-10.
    """

    SCHEDULED = "scheduled"
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class ReminderReason(enum.StrEnum):
    """Catálogo cerrado de motivos de un job saltado, cancelado o fallado (C-09, D1)."""

    NO_CONSENT = "no_consent"
    NO_RECIPIENT = "no_recipient"
    APPOINTMENT_STARTED = "appointment_started"
    APPOINTMENT_INACTIVE = "appointment_inactive"
    STEP_ELAPSED = "step_elapsed"
    STEP_REMOVED = "step_removed"
    RESCHEDULED = "rescheduled"
    CONFIRMED = "confirmed"
    TEMPLATE_INACTIVE = "template_inactive"
    PROVIDER_REJECTED = "provider_rejected"
    SEND_FAILED = "send_failed"
    LEASE_EXPIRED = "lease_expired"


class ConsentStatus(enum.StrEnum):
    """Estado de un consentimiento por canal (C-09)."""

    OPT_IN = "opt_in"
    OPT_OUT = "opt_out"


class ConsentSource(enum.StrEnum):
    """Quién originó un cambio de consentimiento; `legacy` es el backfill previo a C-09."""

    BOOKING = "booking"
    WHATSAPP_REPLY = "whatsapp_reply"
    RECEPTION = "reception"
    LEGACY = "legacy"


class DeliveryEventType(enum.StrEnum):
    """Hecho registrado en `delivery_event` (append-only, C-09; `delivered`/`read` en C-10)."""

    SENT = "sent"
    ATTEMPT_FAILED = "attempt_failed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    ESCALATED = "escalated"
    LEASE_EXPIRED = "lease_expired"
    DELIVERED = "delivered"
    READ = "read"


# Vigente = ocupa agenda (RN-AG-01); `absent`, `no_show` y `cancelled` liberan el hueco.
VIGENT_STATUSES = (
    AppointmentStatus.PENDING,
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.PRESENT,
)
