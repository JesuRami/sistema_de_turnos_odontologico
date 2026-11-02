"""Normalización de teléfonos a E.164 (SU-03: el teléfono identifica al paciente).

El mensaje de error NUNCA incluye el valor ingresado (regla dura 13: sin PII
en logs ni en errores).
"""

import phonenumbers

DEFAULT_REGION = "AR"
_INVALID_MESSAGE = "Teléfono inválido"


class InvalidPhoneError(ValueError):
    """Teléfono no normalizable; el mensaje es genérico a propósito."""

    def __init__(self) -> None:
        super().__init__(_INVALID_MESSAGE)


def normalize_phone_e164(raw: str, region: str = DEFAULT_REGION) -> str:
    """Devuelve `raw` en E.164 (`+549...`); una entrada nacional usa `region`.

    Lanza `InvalidPhoneError` (sin el valor en el mensaje) si no es un número válido.
    """
    try:
        number = phonenumbers.parse(raw, region)
    except phonenumbers.NumberParseException:
        raise InvalidPhoneError from None
    if not phonenumbers.is_valid_number(number):
        raise InvalidPhoneError
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
