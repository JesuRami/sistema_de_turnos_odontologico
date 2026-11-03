"""Modelos ORM del dominio core (C-02/C-03). Importar registra todo en `Base.metadata`."""

from app.models.auth_event import AuthEvent
from app.models.base import Base
from app.models.chair import Chair
from app.models.clinic import Clinic
from app.models.enums import AuthEventType, UserRole
from app.models.patient import Patient
from app.models.professional import Professional
from app.models.schedule_rule import ScheduleRule
from app.models.user import User

__all__ = [
    "AuthEvent",
    "AuthEventType",
    "Base",
    "Chair",
    "Clinic",
    "Patient",
    "Professional",
    "ScheduleRule",
    "User",
    "UserRole",
]
