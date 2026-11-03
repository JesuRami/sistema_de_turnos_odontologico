"""Modelos ORM del dominio core (C-02/C-03/C-04). Importar registra todo en `Base.metadata`."""

from app.models.agenda_config_event import AgendaConfigEvent
from app.models.auth_event import AuthEvent
from app.models.base import Base
from app.models.block import Block
from app.models.chair import Chair
from app.models.clinic import Clinic
from app.models.enums import (
    AuthEventType,
    BlockReason,
    ConfigAction,
    ConfigEntity,
    UserRole,
)
from app.models.patient import Patient
from app.models.professional import Professional
from app.models.schedule_rule import ScheduleRule
from app.models.user import User

__all__ = [
    "AgendaConfigEvent",
    "AuthEvent",
    "AuthEventType",
    "Base",
    "Block",
    "BlockReason",
    "Chair",
    "Clinic",
    "ConfigAction",
    "ConfigEntity",
    "Patient",
    "Professional",
    "ScheduleRule",
    "User",
    "UserRole",
]
