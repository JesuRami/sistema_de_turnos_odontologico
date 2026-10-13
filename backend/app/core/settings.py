"""Configuración 12-factor vía entorno (pydantic-settings) con falla rápida.

Toda clave requerida ausente aborta el arranque nombrando la variable
(regla dura 6: secretos solo vía env; nunca defaults inseguros).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings de la aplicación (fuente única: variables de entorno)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Requeridas (sin defaults inseguros — falla rápida si faltan).
    DATABASE_URL: str
    REDIS_URL: str
    JWT_SECRET: str

    # JWT / auth (C-03 materializa refresh/blacklist en Redis).
    JWT_ALGORITHM: str = "HS256"
    JWT_ISSUER: str = "turnos-odontologico"
    JWT_AUDIENCE: str = "turnos-odontologico-api"
    JWT_ACCESS_MINUTES: int = 15
    JWT_REFRESH_DAYS: int = 7

    # Reserva pública / tokens de gestión.
    BOOKING_RATE_LIMIT: str = "30/minute"
    MANAGE_TOKEN_TTL_H: int = 72
    FRONTEND_PUBLIC_URL: str = "http://localhost:5173"
    CORS_ORIGINS: str = "http://localhost:5173"

    # Clínica / zona horaria.
    CLINIC_TZ_DEFAULT: str = "America/Argentina/Buenos_Aires"
    ENV: str = "dev"

    # WhatsApp Cloud API (C-09/C-10; en C-01 solo claves, sin envío real).
    WHATSAPP_TOKEN: str = ""
    META_APP_ID: str = ""
    META_APP_SECRET: str = ""
    META_PHONE_NUMBER_ID: str = ""
    META_API_VERSION: str = "v19.0"
    META_VERIFY_TOKEN: str = ""

    # Email transaccional (canal de respaldo; proveedor a definir).
    EMAIL_HOST: str = ""
    EMAIL_PORT: int = 587
    EMAIL_USER: str = ""
    EMAIL_PASSWORD: str = ""
    EMAIL_FROM: str = ""

    # Worker async (scheduler real en C-09; en C-01 solo concurrencia).
    REMINDER_WORKER_CONCURRENCY: int = 10


def get_settings() -> Settings:
    """Construye Settings desde el entorno (falla rápido si falta requerida)."""
    return Settings()  # type: ignore[call-arg]
