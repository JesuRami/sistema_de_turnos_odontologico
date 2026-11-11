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
    # C-12: creado al aceptar una oferta de la lista de espera (nace `confirmed`).
    WAITLIST = "waitlist"


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
    # C-12: la oferta del job ya no está pendiente o venció.
    OFFER_CLOSED = "offer_closed"


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


class WhatsAppIntent(enum.StrEnum):
    """Intención de un mensaje entrante del paciente (C-10, D7)."""

    CONFIRM = "confirm"
    CHANGE = "change"
    STOP = "stop"
    UNKNOWN = "unknown"
    # C-12 (D8): respuesta a una oferta de la lista de espera.
    ACCEPT_OFFER = "accept_offer"
    DECLINE_OFFER = "decline_offer"


class WhatsAppReplyKind(enum.StrEnum):
    """Respuesta de sesión que el sistema envía a un entrante (C-10, D7/D8)."""

    CONFIRMED = "confirmed"
    CHANGE_LINK = "change_link"
    CHANGE_CONTACT = "change_contact"
    INACTIVE = "inactive"
    AMBIGUOUS = "ambiguous"
    STOP_ACK = "stop_ack"
    # C-12 (D8): resultado de responder a una oferta de la lista de espera.
    OFFER_ACCEPTED = "offer_accepted"
    OFFER_DECLINED = "offer_declined"
    OFFER_TAKEN = "offer_taken"
    OFFER_CLOSED = "offer_closed"
    OFFER_PATIENT_BUSY = "offer_patient_busy"


class WhatsAppReplyStatus(enum.StrEnum):
    """Estado de una respuesta del outbox (C-10, D8); `sending` es el lease del reclamo."""

    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    EXPIRED = "expired"
    SKIPPED = "skipped"


class WaitingListStatus(enum.StrEnum):
    """Estado de una entrada de la lista de espera (C-12, KB 04)."""

    WAITING = "waiting"
    OFFERED = "offered"
    CONVERTED = "converted"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"


class WaitlistOfferStatus(enum.StrEnum):
    """Estado de una oferta; `cancelled` (no está en la KB) la cierra sin respuesta del paciente."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class WaitlistEventType(enum.StrEnum):
    """Hecho auditado en `waitlist_event` (append-only, C-12, D9)."""

    ENTRY_CREATED = "entry_created"
    ENTRY_UPDATED = "entry_updated"
    ENTRY_PRIORITIZED = "entry_prioritized"
    ENTRY_UNPRIORITIZED = "entry_unprioritized"
    ENTRY_WITHDRAWN = "entry_withdrawn"
    ENTRY_EXPIRED = "entry_expired"
    ENTRY_CONVERTED = "entry_converted"
    OFFER_CREATED = "offer_created"
    OFFER_ACCEPTED = "offer_accepted"
    OFFER_DECLINED = "offer_declined"
    OFFER_EXPIRED = "offer_expired"
    OFFER_CANCELLED = "offer_cancelled"


ACTIVE_ENTRY_STATUSES = (WaitingListStatus.WAITING, WaitingListStatus.OFFERED)

# Vigente = ocupa agenda (RN-AG-01); `absent`, `no_show` y `cancelled` liberan el hueco.
VIGENT_STATUSES = (
    AppointmentStatus.PENDING,
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.PRESENT,
)


# --------------------------------------------------------------------------- C-15 clínica


class ToothSurface(enum.StrEnum):
    """Cara de una pieza FDI (C-15). `O` es oclusal (posteriores) o incisal (anteriores)."""

    M = "M"
    D = "D"
    O = "O"  # noqa: E741 - nombre clínico estándar de la cara
    V = "V"
    L = "L"
    W = "W"  # pieza completa


class EvolutionKind(enum.StrEnum):
    """Entrada original o corrección (que nunca reescribe a la original, Ley 26.529)."""

    ENTRY = "entry"
    CORRECTION = "correction"


class AttachmentKind(enum.StrEnum):
    """Tipo clínico declarado de un adjunto (el tipo de contenido se verifica aparte)."""

    XRAY = "xray"
    PHOTO = "photo"
    DOCUMENT = "document"
    OTHER = "other"


class PlanDecision(enum.StrEnum):
    """Decisión registrada sobre una versión de presupuesto (append-only)."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ClinicalAction(enum.StrEnum):
    """Acción auditada en `clinical_access_event` (lecturas y escrituras clínicas)."""

    RECORD_OPEN = "record_open"
    RECORD_READ = "record_read"
    ANAMNESIS_WRITE = "anamnesis_write"
    ANAMNESIS_READ = "anamnesis_read"
    ODONTOGRAM_WRITE = "odontogram_write"
    ODONTOGRAM_READ = "odontogram_read"
    ODONTOGRAM_HISTORY_READ = "odontogram_history_read"
    EVOLUTION_WRITE = "evolution_write"
    EVOLUTION_CORRECT = "evolution_correct"
    EVOLUTION_READ = "evolution_read"
    ATTACHMENT_UPLOAD = "attachment_upload"
    ATTACHMENT_LIST = "attachment_list"
    ATTACHMENT_DOWNLOAD = "attachment_download"
    ATTACHMENT_REMOVE = "attachment_remove"
    PLAN_WRITE = "plan_write"
    PLAN_VERSION_WRITE = "plan_version_write"
    PLAN_DECISION = "plan_decision"
    PLAN_LIST = "plan_list"
    PLAN_READ = "plan_read"
    PLAN_PDF_EXPORT = "plan_pdf_export"
    ACCESS_LOG_READ = "access_log_read"
