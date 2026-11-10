"""Configuración 12-factor vía entorno (pydantic-settings) con falla rápida.

Toda clave requerida ausente aborta el arranque nombrando la variable
(regla dura 6: secretos solo vía env; nunca defaults inseguros).

C-03 agrega la validación del secreto JWT (≥32 bytes, algoritmo pineado), los
límites de rate-limit de auth y los flags de la cookie de refresh.
"""

from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.rate_limit import parse_window_spec

_JWT_MIN_SECRET_BYTES = 32
_JWT_MAX_ACCESS_MINUTES = 15
_LINK_MIN_SECRET_BYTES = 32


def parse_backoff_minutes(valor: str) -> tuple[int, ...]:
    """`"5,30,120"` → `(5, 30, 120)`; todo tramo debe ser un entero positivo."""
    try:
        tramos = tuple(int(parte) for parte in valor.split(","))
    except ValueError:
        raise ValueError("debe ser una lista de minutos separada por comas") from None
    if not tramos or any(t < 1 for t in tramos):
        raise ValueError("cada tramo debe ser un entero positivo")
    return tramos


class SettingsError(RuntimeError):
    """Configuración insegura: aborta el arranque con un mensaje que no filtra valores.

    Se usa una excepción propia (no `ValueError`) a propósito: pydantic adjunta
    el valor de entrada a los `ValidationError`, y para `JWT_SECRET` eso
    significaría imprimir el secreto en el arranque.
    """


class Settings(BaseSettings):
    """Settings de la aplicación (fuente única: variables de entorno)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Requeridas (sin defaults inseguros — falla rápida si faltan).
    DATABASE_URL: str
    REDIS_URL: str
    JWT_SECRET: SecretStr

    # JWT / auth (C-03 materializa refresh/rotación en Redis).
    JWT_ALGORITHM: str = "HS256"
    JWT_ISSUER: str = "turnos-odontologico"
    JWT_AUDIENCE: str = "turnos-odontologico-api"
    JWT_ACCESS_MINUTES: int = 15
    JWT_REFRESH_DAYS: int = 7

    # Rate-limit de autenticación (Redis compartido; valores no secretos).
    AUTH_LOGIN_RATE_LIMIT: str = "5/60s"
    AUTH_LOGIN_IP_RATE_LIMIT: str = "30/60s"
    AUTH_REFRESH_RATE_LIMIT: str = "60/60s"
    AUTH_PASSWORD_RATE_LIMIT: str = "5/60s"

    # Sesiones de auth en una base lógica propia de Redis (no secreta).
    REDIS_AUTH_DB: int = Field(default=15, ge=0, le=15)

    # Cookie de refresh: en prod se usa `__Host-` y `Domain` debe quedar vacío.
    COOKIE_DOMAIN: str = ""

    # Reserva pública / tokens de gestión.
    BOOKING_RATE_LIMIT: str = "30/minute"
    MANAGE_TOKEN_TTL_H: int = Field(default=72, ge=1)
    # Gestión por token (C-08, D10): cupos estrictos por IP y por token (el hash es la clave).
    MANAGE_READ_IP_RATE_LIMIT: str = "120/60s"
    MANAGE_READ_TOKEN_RATE_LIMIT: str = "60/60s"
    MANAGE_WRITE_IP_RATE_LIMIT: str = "30/60s"
    MANAGE_WRITE_TOKEN_RATE_LIMIT: str = "10/60s"
    # Reserva pública (C-07, D2/D14): cupos Redis `<intentos>/<segundos>s`, horizonte y versión
    # de la política de privacidad aceptada. `BOOKING_RATE_LIMIT` (arriba) sigue siendo el tope
    # global en memoria de C-01; estos cupos son los estrictos por IP / clínica.
    PUBLIC_BOOKING_IP_RATE_LIMIT: str = "10/3600s"
    PUBLIC_BOOKING_SLUG_RATE_LIMIT: str = "300/3600s"
    PUBLIC_BOOKING_READ_RATE_LIMIT: str = "120/60s"
    PUBLIC_BOOKING_HORIZON_DAYS: int = Field(default=60, ge=1)
    PRIVACY_POLICY_VERSION: str = "2026-11-placeholder"
    BOT_GUARD: str = "noop"
    # Lista de espera (C-12, D3/D4/D7): anotación pública con cupos propios, ventana mínima de
    # una oferta automática, vencimientos consecutivos tolerados y tamaño de lote del tick.
    WAITLIST_PUBLIC_IP_RATE_LIMIT: str = "5/3600s"
    WAITLIST_PUBLIC_SLUG_RATE_LIMIT: str = "100/3600s"
    WAITLIST_MIN_LEAD_MINUTES: int = Field(default=60, ge=0)
    WAITLIST_MIN_OFFER_WINDOW_MINUTES: int = Field(default=15, ge=1)
    WAITLIST_MAX_CONSECUTIVE_EXPIRED: int = Field(default=3, ge=1)
    WAITLIST_TICK_BATCH_SIZE: int = Field(default=100, ge=1, le=1000)
    FRONTEND_PUBLIC_URL: str = "http://localhost:5173"
    CORS_ORIGINS: str = "http://localhost:5173"

    # Clínica / zona horaria.
    CLINIC_TZ_DEFAULT: str = "America/Argentina/Buenos_Aires"
    ENV: str = "dev"

    # WhatsApp Cloud API (C-10, D3). Con `REMINDER_WHATSAPP_PROVIDER=meta` son obligatorias
    # (token, secreto de app, número compartido por defecto y token de verificación del webhook).
    WHATSAPP_TOKEN: SecretStr = SecretStr("")
    META_APP_ID: str = ""
    META_APP_SECRET: SecretStr = SecretStr("")
    META_PHONE_NUMBER_ID: str = ""
    META_API_VERSION: str = "v19.0"
    META_VERIFY_TOKEN: SecretStr = SecretStr("")
    # Base de la Graph API (configurable para tests con transporte local).
    META_GRAPH_BASE_URL: str = "https://graph.facebook.com"
    WHATSAPP_HTTP_TIMEOUT_S: float = Field(default=10, gt=0)
    # Tope del cuerpo del webhook (bytes); más grande → 413 sin leer el resto.
    WHATSAPP_WEBHOOK_MAX_BYTES: int = Field(default=1024 * 1024, ge=1024)
    # Intentos de una respuesta de sesión (outbox) antes de quedar `failed`.
    WHATSAPP_REPLY_MAX_ATTEMPTS: int = Field(default=3, ge=1)

    # Email transaccional (canal de respaldo; proveedor a definir).
    EMAIL_HOST: str = ""
    EMAIL_PORT: int = 587
    EMAIL_USER: str = ""
    EMAIL_PASSWORD: str = ""
    EMAIL_FROM: str = ""

    # Worker async y motor de recordatorios (C-09, D10/D12/D13).
    REMINDER_WORKER_CONCURRENCY: int = Field(default=10, ge=1)
    # `disabled`: el worker no reclama los jobs del canal y nunca los marca enviados.
    # `meta` envía por la Cloud API (C-10); exige las credenciales META_*/WHATSAPP_TOKEN.
    REMINDER_WHATSAPP_PROVIDER: Literal["disabled", "fake", "meta"] = "disabled"
    REMINDER_EMAIL_PROVIDER: Literal["disabled", "smtp", "fake"] = "disabled"
    REMINDER_MAX_ATTEMPTS: int = Field(default=3, ge=1)
    # Espera tras el 1.er, 2.º… fallo; el tramo i vale tras el fallo i+1.
    REMINDER_BACKOFF_MINUTES: str = "5,30,120"
    REMINDER_LEASE_MINUTES: int = Field(default=5, ge=1)
    REMINDER_TICK_BUDGET_S: int = Field(default=50, ge=1)
    REMINDER_BATCH_SIZE: int = Field(default=100, ge=1)
    # Costo estimado por mensaje en USD × 10⁻⁶ (RN-WA-05); 0 hasta tener precios.
    REMINDER_COST_WHATSAPP_MICROS: int = Field(default=0, ge=0)
    REMINDER_COST_EMAIL_MICROS: int = Field(default=0, ge=0)
    # Reenvío manual desde recepción (C-11, D6): espera mínima entre reenvíos del mismo job y
    # tope de reenvíos por job y día local de la clínica (anti doble clic y anti spam).
    REMINDER_MANUAL_RESEND_COOLDOWN_S: int = Field(default=60, ge=0)
    REMINDER_MANUAL_RESEND_MAX_PER_DAY: int = Field(default=3, ge=1)
    # Firma de los links de gestión de los mensajes (D9). Vacío solo se admite en `dev`
    # (los links firmados quedan deshabilitados); nunca se imprime.
    MANAGE_LINK_SECRET: SecretStr = SecretStr("")

    @property
    def reminder_backoff_minutes(self) -> tuple[int, ...]:
        return parse_backoff_minutes(self.REMINDER_BACKOFF_MINUTES)

    @field_validator("REMINDER_BACKOFF_MINUTES")
    @classmethod
    def _validar_backoff(cls, valor: str) -> str:
        parse_backoff_minutes(valor)
        return valor

    @field_validator(
        "AUTH_LOGIN_RATE_LIMIT",
        "AUTH_LOGIN_IP_RATE_LIMIT",
        "AUTH_REFRESH_RATE_LIMIT",
        "AUTH_PASSWORD_RATE_LIMIT",
        "PUBLIC_BOOKING_IP_RATE_LIMIT",
        "PUBLIC_BOOKING_SLUG_RATE_LIMIT",
        "PUBLIC_BOOKING_READ_RATE_LIMIT",
        "MANAGE_READ_IP_RATE_LIMIT",
        "MANAGE_READ_TOKEN_RATE_LIMIT",
        "MANAGE_WRITE_IP_RATE_LIMIT",
        "MANAGE_WRITE_TOKEN_RATE_LIMIT",
        "WAITLIST_PUBLIC_IP_RATE_LIMIT",
        "WAITLIST_PUBLIC_SLUG_RATE_LIMIT",
    )
    @classmethod
    def _validar_rate_limit(cls, valor: str) -> str:
        """Valida `<intentos>/<segundos>s` al arrancar (no en el request)."""
        parse_window_spec(valor)
        return valor

    @model_validator(mode="after")
    def _validar_seguridad(self) -> "Settings":
        """Controles que deben abortar el arranque sin filtrar el secreto.

        Se ejecuta después de la coerción y lanza `SettingsError` (no
        `ValidationError`) para que pydantic no adjunte el valor de entrada.
        """
        if len(self.JWT_SECRET.get_secret_value().encode("utf-8")) < _JWT_MIN_SECRET_BYTES:
            raise SettingsError(
                f"JWT_SECRET debe tener al menos {_JWT_MIN_SECRET_BYTES} bytes; "
                "generar con `openssl rand -hex 32`"
            )
        if self.JWT_ALGORITHM != "HS256":
            raise SettingsError("JWT_ALGORITHM solo admite HS256 en v1")
        if not 1 <= self.JWT_ACCESS_MINUTES <= _JWT_MAX_ACCESS_MINUTES:
            raise SettingsError(
                f"JWT_ACCESS_MINUTES debe estar entre 1 y {_JWT_MAX_ACCESS_MINUTES}"
            )
        if self.JWT_REFRESH_DAYS < 1:
            raise SettingsError("JWT_REFRESH_DAYS debe ser mayor o igual a 1")
        link_secret = self.MANAGE_LINK_SECRET.get_secret_value()
        if link_secret or self.ENV != "dev":
            if len(link_secret.encode("utf-8")) < _LINK_MIN_SECRET_BYTES:
                raise SettingsError(
                    f"MANAGE_LINK_SECRET debe tener al menos {_LINK_MIN_SECRET_BYTES} bytes; "
                    "generar con `openssl rand -hex 32`"
                )
        if self.REMINDER_WHATSAPP_PROVIDER == "meta":
            requeridas = {
                "WHATSAPP_TOKEN": self.WHATSAPP_TOKEN.get_secret_value(),
                "META_APP_SECRET": self.META_APP_SECRET.get_secret_value(),
                "META_PHONE_NUMBER_ID": self.META_PHONE_NUMBER_ID,
                "META_VERIFY_TOKEN": self.META_VERIFY_TOKEN.get_secret_value(),
            }
            faltan = [nombre for nombre, valor in requeridas.items() if not valor.strip()]
            if faltan:
                raise SettingsError(
                    "REMINDER_WHATSAPP_PROVIDER=meta exige configurar: " + ", ".join(faltan)
                )
        if len(self.reminder_backoff_minutes) < self.REMINDER_MAX_ATTEMPTS - 1:
            raise SettingsError(
                "REMINDER_BACKOFF_MINUTES debe tener al menos REMINDER_MAX_ATTEMPTS - 1 tramos"
            )
        return self


def get_settings() -> Settings:
    """Construye Settings desde el entorno (falla rápido si falta requerida)."""
    return Settings()  # type: ignore[call-arg]
