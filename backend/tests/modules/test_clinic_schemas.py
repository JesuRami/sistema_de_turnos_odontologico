"""Schema de borde `ReminderStep` (extra='forbid', canal cerrado, offset positivo)."""

import pytest
from app.modules.clinic.schemas import ReminderStep
from pydantic import ValidationError


@pytest.mark.parametrize("channel", ["whatsapp", "email"])
def test_paso_valido(channel: str) -> None:
    step = ReminderStep.model_validate({"offset_h": 24, "channel": channel})
    assert step.offset_h == 24
    assert step.channel == channel


@pytest.mark.parametrize(
    "payload",
    [
        {"offset_h": 24, "channel": "sms"},
        {"offset_h": 0, "channel": "whatsapp"},
        {"offset_h": -3, "channel": "whatsapp"},
        {"offset_h": 24, "channel": "whatsapp", "extra": 1},
        {"channel": "whatsapp"},
    ],
)
def test_paso_invalido_rechazado(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ReminderStep.model_validate(payload)
