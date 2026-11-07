"""Estado efectivo de un paso a partir de sus eventos (C-11, D2; spec delivery-timeline).

Unitario puro: la precedencia `read > delivered > failed` se acota a la última generación de
envío (posterior al último reenvío manual) y tolera el redondeo a segundos de Meta.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models import DeliveryEventType, ReminderStatus
from app.modules.reminders.timeline import TimelineEvent, effective_status, mark_generations

T0 = datetime(2030, 1, 10, 12, 0, 0, 700000, tzinfo=UTC)
S = DeliveryEventType.SENT
D = DeliveryEventType.DELIVERED
R = DeliveryEventType.READ
F = DeliveryEventType.FAILED


def _ev(tipo: DeliveryEventType | str, segundos: float) -> TimelineEvent:
    return TimelineEvent(
        type=tipo.value if isinstance(tipo, DeliveryEventType) else tipo,
        occurred_at=T0 + timedelta(seconds=segundos),
        detail={},
    )


def test_enviado_entregado_leido_da_leido() -> None:
    eventos = [_ev(S, 0), _ev(D, 60), _ev(R, 120)]

    assert effective_status(ReminderStatus.READ, eventos, None) == "read"


def test_entregado_y_fallido_del_mismo_mensaje_da_entregado() -> None:
    eventos = [_ev(S, 0), _ev(D, 60), _ev(F, 90)]

    assert effective_status(ReminderStatus.DELIVERED, eventos, None) == "delivered"


def test_leido_sin_entregado_da_leido() -> None:
    eventos = [_ev(S, 0), _ev(R, 60)]

    assert effective_status(ReminderStatus.READ, eventos, None) == "read"


def test_ultimo_intento_fallido_da_fallido() -> None:
    eventos = [_ev(S, 0), _ev(F, 30)]

    assert effective_status(ReminderStatus.FAILED, eventos, None) == "failed"


def test_entrega_con_timestamp_truncado_de_meta_cuenta() -> None:
    # Meta informa en segundos: el `delivered` puede quedar 0,7 s "antes" del `sent` del motor.
    eventos = [_ev(S, 0), _ev(D, -0.7)]

    assert effective_status(ReminderStatus.DELIVERED, eventos, None) == "delivered"


def test_sin_envio_usa_el_estado_del_job() -> None:
    assert effective_status(ReminderStatus.SKIPPED, [_ev("skipped", 0)], None) == "skipped"


def test_reenvio_pendiente_no_hereda_el_fallo_anterior() -> None:
    eventos = [_ev(S, 0), _ev(F, 30), _ev("manual_resend", 600)]
    corte = T0 + timedelta(seconds=600)

    assert effective_status(ReminderStatus.SCHEDULED, eventos, corte) == "scheduled"


def test_reenvio_entregado_no_hereda_el_leido_anterior_ni_el_fallo() -> None:
    eventos = [
        _ev(S, 0),
        _ev(R, 30),
        _ev("manual_resend", 600),
        _ev(S, 660),
        _ev(F, 700),
    ]
    corte = T0 + timedelta(seconds=600)

    assert effective_status(ReminderStatus.FAILED, eventos, corte) == "failed"


def test_eventos_previos_al_reenvio_quedan_marcados_como_envio_anterior() -> None:
    eventos = [_ev(S, 0), _ev(F, 30), _ev("manual_resend", 600), _ev(S, 660)]
    corte = T0 + timedelta(seconds=600)

    marcados = mark_generations(eventos, corte)

    assert [e.previous for e in marcados] == [True, True, True, False]
