"""`suggest_slots` (C-05 D8): función pura, sin DB. Alternativos ante `409 slot_taken`."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.modules.agenda.availability import RuleWindow, Slot, suggest_slots

BA = ZoneInfo("America/Argentina/Buenos_Aires")
MADRID = ZoneInfo("Europe/Madrid")
LUNES = date(2030, 1, 7)
MEDIA_HORA = timedelta(minutes=30)


def _local(d: date, hh: int, mm: int = 0, tz: ZoneInfo = BA) -> datetime:
    return datetime.combine(d, time(hh, mm), tzinfo=tz)


def _regla(**overrides: object) -> RuleWindow:
    valores: dict[str, object] = {
        "weekday": 0,
        "start_time": time(9, 0),
        "end_time": time(13, 0),
        "slot_duration_min": 30,
        "valid_from": date(2026, 1, 1),
        "valid_to": None,
    }
    valores.update(overrides)
    return RuleWindow(**valores)  # type: ignore[arg-type]


def _inicios(slots: list[Slot], tz: ZoneInfo = BA) -> list[str]:
    return [s.starts_at.astimezone(tz).strftime("%Y-%m-%d %H:%M") for s in slots]


def _sugerir(
    *,
    rules: list[RuleWindow] | None = None,
    blocks: list[tuple[datetime, datetime]] | None = None,
    busy: list[tuple[datetime, datetime]] | None = None,
    desde: datetime | None = None,
    duration: timedelta = MEDIA_HORA,
    buffer: timedelta = timedelta(0),
    now: datetime | None = None,
    tz: ZoneInfo = BA,
    n: int = 3,
) -> list[Slot]:
    return suggest_slots(
        rules if rules is not None else [_regla()],
        blocks=blocks or [],
        busy=busy or [],
        desde=desde or _local(LUNES, 10),
        tz=tz,
        duration=duration,
        buffer=buffer,
        now=now or _local(LUNES, 8),
        n=n,
    )


def test_alternativos_del_mismo_dia_en_orden_cronologico() -> None:
    ocupado = (_local(LUNES, 10), _local(LUNES, 10, 30))
    slots = _sugerir(busy=[ocupado])
    assert _inicios(slots) == ["2030-01-07 10:30", "2030-01-07 11:00", "2030-01-07 11:30"]
    assert all(s.ends_at - s.starts_at == MEDIA_HORA for s in slots)


def test_ocupados_incluyen_el_buffer_del_turno_existente() -> None:
    ocupado = (_local(LUNES, 10), _local(LUNES, 10, 40))  # 30 min + 10 de buffer
    assert _inicios(_sugerir(busy=[ocupado])) == [
        "2030-01-07 11:00",
        "2030-01-07 11:30",
        "2030-01-07 12:00",
    ]


def test_el_buffer_del_candidato_no_puede_pisar_un_turno_siguiente() -> None:
    siguiente = (_local(LUNES, 10, 30), _local(LUNES, 11))
    slots = _sugerir(busy=[siguiente], buffer=timedelta(minutes=10))
    assert _inicios(slots)[0] == "2030-01-07 11:00"


def test_bloqueos_y_pasado_quedan_fuera() -> None:
    bloqueo = (_local(LUNES, 10), _local(LUNES, 12))
    slots = _sugerir(blocks=[bloqueo], desde=_local(LUNES, 9), now=_local(LUNES, 9, 15))
    assert _inicios(slots) == ["2030-01-07 09:30", "2030-01-07 12:00", "2030-01-07 12:30"]


def test_el_turno_debe_entrar_completo_en_la_franja() -> None:
    slots = _sugerir(desde=_local(LUNES, 12), duration=timedelta(minutes=45), n=5)
    assert _inicios(slots)[:2] == ["2030-01-07 12:00", "2030-01-14 09:00"]


def test_salta_a_la_semana_siguiente_y_respeta_vigencia() -> None:
    reglas = [
        _regla(valid_to=LUNES + timedelta(days=7)),
        _regla(weekday=2, valid_from=date(2031, 1, 1)),
    ]
    slots = _sugerir(rules=reglas, desde=_local(LUNES, 12, 30), n=3)
    assert _inicios(slots) == ["2030-01-07 12:30", "2030-01-14 09:00", "2030-01-14 09:30"]


def test_sin_huecos_en_14_dias_devuelve_vacio() -> None:
    todo = (_local(LUNES, 0), _local(LUNES + timedelta(days=30), 0))
    assert _sugerir(busy=[todo]) == []


def test_horizonte_de_14_dias() -> None:
    reglas = [_regla(valid_from=LUNES + timedelta(days=15))]
    assert _sugerir(rules=reglas) == []


def test_cambio_de_horario_de_la_zona() -> None:
    """Europe/Madrid pasa a horario de verano el domingo 2030-03-31: la grilla es local."""
    domingo = date(2030, 3, 24)
    regla = _regla(weekday=6, start_time=time(9, 0), end_time=time(10, 0))
    slots = _sugerir(
        rules=[regla],
        desde=_local(domingo, 0, tz=MADRID),
        now=_local(domingo, 0, tz=MADRID),
        tz=MADRID,
        n=4,
    )
    assert _inicios(slots, MADRID) == [
        "2030-03-24 09:00",
        "2030-03-24 09:30",
        "2030-03-31 09:00",
        "2030-03-31 09:30",
    ]
    assert [s.starts_at.astimezone(UTC).hour for s in slots] == [8, 8, 7, 7]


def test_hora_inexistente_por_cambio_de_horario_se_omite() -> None:
    domingo = date(2030, 3, 31)  # 02:00 → 03:00 en Madrid
    regla = _regla(weekday=6, start_time=time(1, 0), end_time=time(4, 0), slot_duration_min=60)
    slots = _sugerir(
        rules=[regla],
        desde=_local(domingo, 0, tz=MADRID),
        now=_local(domingo, 0, tz=MADRID),
        duration=timedelta(minutes=60),
        tz=MADRID,
        n=2,
    )
    assert _inicios(slots, MADRID) == ["2030-03-31 01:00", "2030-03-31 03:00"]
