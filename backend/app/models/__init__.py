"""Modelos ORM del dominio core (C-02 a C-06). Importar registra todo en `Base.metadata`."""

from app.models.agenda_config_event import AgendaConfigEvent
from app.models.appointment import Appointment
from app.models.appointment_event import AppointmentEvent
from app.models.auth_event import AuthEvent
from app.models.base import Base
from app.models.block import Block
from app.models.chair import Chair
from app.models.clinic import Clinic
from app.models.consent import Consent
from app.models.delivery_event import DeliveryEvent
from app.models.enums import (
    VIGENT_STATUSES,
    ActorType,
    AppointmentEventType,
    AppointmentOrigin,
    AppointmentStatus,
    AuthEventType,
    BlockReason,
    CancellationReason,
    ConfigAction,
    ConfigEntity,
    ConsentSource,
    ConsentStatus,
    DeliveryEventType,
    ReminderChannel,
    ReminderReason,
    ReminderStatus,
    UserRole,
)
from app.models.notification_template import NotificationTemplate
from app.models.patient import Patient
from app.models.patient_merge import PatientMerge
from app.models.professional import Professional
from app.models.reminder_job import ReminderJob
from app.models.schedule_rule import ScheduleRule
from app.models.user import User

__all__ = [
    "VIGENT_STATUSES",
    "ActorType",
    "AgendaConfigEvent",
    "Appointment",
    "AppointmentEvent",
    "AppointmentEventType",
    "AppointmentOrigin",
    "AppointmentStatus",
    "AuthEvent",
    "AuthEventType",
    "Base",
    "Block",
    "BlockReason",
    "CancellationReason",
    "Chair",
    "Clinic",
    "ConfigAction",
    "ConfigEntity",
    "Consent",
    "ConsentSource",
    "ConsentStatus",
    "DeliveryEvent",
    "DeliveryEventType",
    "NotificationTemplate",
    "Patient",
    "PatientMerge",
    "Professional",
    "ReminderChannel",
    "ReminderJob",
    "ReminderReason",
    "ReminderStatus",
    "ScheduleRule",
    "User",
    "UserRole",
]
