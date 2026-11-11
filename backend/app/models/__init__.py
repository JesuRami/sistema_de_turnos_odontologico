"""Modelos ORM del dominio (C-02 a C-15). Importar registra todo en `Base.metadata`."""

from app.models.agenda_config_event import AgendaConfigEvent
from app.models.anamnesis_version import AnamnesisVersion
from app.models.appointment import Appointment
from app.models.appointment_event import AppointmentEvent
from app.models.auth_event import AuthEvent
from app.models.base import Base
from app.models.block import Block
from app.models.chair import Chair
from app.models.clinic import Clinic
from app.models.clinical_access_event import ClinicalAccessEvent
from app.models.clinical_attachment import ClinicalAttachment, ClinicalAttachmentRemoval
from app.models.clinical_evolution import ClinicalEvolution
from app.models.clinical_record import ClinicalRecord
from app.models.consent import Consent
from app.models.delivery_event import DeliveryEvent
from app.models.enums import (
    ACTIVE_ENTRY_STATUSES,
    VIGENT_STATUSES,
    ActorType,
    AppointmentEventType,
    AppointmentOrigin,
    AppointmentStatus,
    AttachmentKind,
    AuthEventType,
    BlockReason,
    CancellationReason,
    ClinicalAction,
    ConfigAction,
    ConfigEntity,
    ConsentSource,
    ConsentStatus,
    DeliveryEventType,
    EvolutionKind,
    PlanDecision,
    ReminderChannel,
    ReminderReason,
    ReminderStatus,
    ToothSurface,
    UserRole,
    WaitingListStatus,
    WaitlistEventType,
    WaitlistOfferStatus,
    WhatsAppIntent,
    WhatsAppReplyKind,
    WhatsAppReplyStatus,
)
from app.models.notification_template import NotificationTemplate
from app.models.odontogram_condition import OdontogramCondition
from app.models.odontogram_event import OdontogramEvent
from app.models.patient import Patient
from app.models.patient_merge import PatientMerge
from app.models.professional import Professional
from app.models.reminder_job import ReminderJob
from app.models.reminder_manual_resend import ReminderManualResend
from app.models.schedule_rule import ScheduleRule
from app.models.treatment_plan import (
    TreatmentPlan,
    TreatmentPlanDecision,
    TreatmentPlanItem,
    TreatmentPlanVersion,
)
from app.models.user import User
from app.models.waiting_list import WaitingListEntry, WaitlistEvent, WaitlistOffer
from app.models.whatsapp_inbound import WhatsAppInbound
from app.models.whatsapp_outbound_reply import WhatsAppOutboundReply

__all__ = [
    "ACTIVE_ENTRY_STATUSES",
    "VIGENT_STATUSES",
    "ActorType",
    "AgendaConfigEvent",
    "AnamnesisVersion",
    "Appointment",
    "AppointmentEvent",
    "AppointmentEventType",
    "AppointmentOrigin",
    "AppointmentStatus",
    "AttachmentKind",
    "AuthEvent",
    "AuthEventType",
    "Base",
    "Block",
    "BlockReason",
    "CancellationReason",
    "Chair",
    "Clinic",
    "ClinicalAccessEvent",
    "ClinicalAction",
    "ClinicalAttachment",
    "ClinicalAttachmentRemoval",
    "ClinicalEvolution",
    "ClinicalRecord",
    "ConfigAction",
    "ConfigEntity",
    "Consent",
    "ConsentSource",
    "ConsentStatus",
    "DeliveryEvent",
    "DeliveryEventType",
    "EvolutionKind",
    "NotificationTemplate",
    "OdontogramCondition",
    "OdontogramEvent",
    "Patient",
    "PatientMerge",
    "PlanDecision",
    "Professional",
    "ReminderChannel",
    "ReminderJob",
    "ReminderManualResend",
    "ReminderReason",
    "ReminderStatus",
    "ScheduleRule",
    "ToothSurface",
    "TreatmentPlan",
    "TreatmentPlanDecision",
    "TreatmentPlanItem",
    "TreatmentPlanVersion",
    "User",
    "UserRole",
    "WaitingListEntry",
    "WaitingListStatus",
    "WaitlistEvent",
    "WaitlistEventType",
    "WaitlistOffer",
    "WaitlistOfferStatus",
    "WhatsAppInbound",
    "WhatsAppIntent",
    "WhatsAppOutboundReply",
    "WhatsAppReplyKind",
    "WhatsAppReplyStatus",
]
