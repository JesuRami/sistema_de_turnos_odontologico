"""Modelos ORM del dominio core (C-02). Importar este paquete registra todo en `Base.metadata`."""

from app.models.base import Base
from app.models.chair import Chair
from app.models.clinic import Clinic
from app.models.enums import UserRole
from app.models.patient import Patient
from app.models.professional import Professional
from app.models.schedule_rule import ScheduleRule
from app.models.user import User

__all__ = [
    "Base",
    "Chair",
    "Clinic",
    "Patient",
    "Professional",
    "ScheduleRule",
    "User",
    "UserRole",
]
