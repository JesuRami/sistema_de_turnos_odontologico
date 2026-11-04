"""Disponibilidad pública (C-07, D3): función pura sobre datos ya leídos, sin DB."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.modules.agenda.availability import RuleWindow
from app.modules.booking_public.availability import (
    ChairRules,
    Scoped,
    chairs_on_grid,
    public_slots,
)

BA = ZoneInfo("America/Argentina/Buenos_Aires")
NY = ZoneInfo("America/New_York")
SILLON_A = uuid.UUID(int=1)
SILLON_B = uuid.UUID(int=2)
LUNES = date(2030, 1, 7)
AHORA = datetime(2030, 1, 7, 8, 0, tzinfo=BA)


def at(hh: int, mm: int = 0, *, days: int = 0) -> datetime:
    return datetime.combine(LUNES + timedelta(days=days), time(hh, mm), tzinfo=BA)


def regla(
    start: time | None = None, end: time | None = None, slot: int = 30, weekday: int = 0
) -> RuleWindow:
    return RuleWindow(
        weekday=weekday,
        start_time=start or time(9),
        end_time=end or time(12),
        slot_duration_min=slot,
        valid_from=date(2026, 1, 1),
        valid_to=None,
    )


def libres(
    chairs: list[ChairRules],
    *,
    blocks: list[Scoped] | None = None,
    busy: list[Scoped] | None = None,
    buffer: int = 0,
    desde: datetime | None = None,
    hasta: datetime | None = None,
    now: datetime = AHORA,
    tz: ZoneInfo = BA,
    cap: int = 500,
) -> list[datetime]:
    slots = public_slots(
        chairs,
        blocks=blocks or [],
        busy=busy or [],
        desde=desde or at(0),
        hasta=hasta or at(0, days=1),
        tz=tz,
        buffer=timedelta(minutes=buffer),
        now=now,
        cap=cap,
    )
    return [s.starts_at.astimezone(tz) for s in slots]


def test_escenario_del_spec_solo_queda_el_9() -> None:
    """Franja 09-12/30 min, buffer 10, turno 10:00, bloqueo 11-12 → solo 09:00."""
    chairs = [ChairRules(SILLON_A, (regla(),))]
    ocupado = Scoped(None, at(10), at(10, 30) + timedelta(minutes=10))
    bloqueo = Scoped(None, at(11), at(12))

    assert libres(chairs, busy=[ocupado], blocks=[bloqueo], buffer=10) == [at(9)]


def test_sin_nada_ocupado_ofrece_toda_la_grilla() -> None:
    chairs = [ChairRules(SILLON_A, (regla(),))]

    assert libres(chairs) == [at(9), at(9, 30), at(10), at(10, 30), at(11), at(11, 30)]


def test_el_slot_expone_inicio_y_fin_de_la_regla() -> None:
    chairs = [ChairRules(SILLON_A, (regla(slot=45, end=time(11)),))]

    slots = public_slots(
        chairs,
        blocks=[],
        busy=[],
        desde=at(0),
        hasta=at(0, days=1),
        tz=BA,
        buffer=timedelta(0),
        now=AHORA,
    )

    assert [(s.starts_at, s.ends_at) for s in slots] == [
        (at(9).astimezone(UTC), at(9, 45).astimezone(UTC)),
        (at(9, 45).astimezone(UTC), at(10, 30).astimezone(UTC)),
    ]


def test_union_de_dos_sillones_deduplica_por_inicio() -> None:
    chairs = [
        ChairRules(SILLON_A, (regla(end=time(10)),)),
        ChairRules(SILLON_B, (regla(start=time(9, 30), end=time(11)),)),
    ]

    assert libres(chairs) == [at(9), at(9, 30), at(10), at(10, 30)]


def test_sillon_ocupado_y_otro_libre_ofrece_el_hueco() -> None:
    chairs = [ChairRules(SILLON_A, (regla(),)), ChairRules(SILLON_B, (regla(),))]
    ocupa_a = Scoped(SILLON_A, at(10), at(10, 30))

    assert at(10) in libres(chairs, busy=[ocupa_a])


def test_ocupado_en_todos_los_sillones_quita_el_hueco() -> None:
    chairs = [ChairRules(SILLON_A, (regla(),)), ChairRules(SILLON_B, (regla(),))]
    busy = [Scoped(SILLON_A, at(10), at(10, 30)), Scoped(SILLON_B, at(10), at(10, 30))]

    assert at(10) not in libres(chairs, busy=busy)


def test_turno_vigente_del_profesional_en_otro_sillon_bloquea_el_hueco() -> None:
    """Un ocupado sin sillón (del profesional) vale para todos los sillones."""
    chairs = [ChairRules(SILLON_A, (regla(),)), ChairRules(SILLON_B, (regla(),))]

    assert at(10) not in libres(chairs, busy=[Scoped(None, at(10), at(10, 30))])


def test_bloqueo_de_un_sillon_no_quita_el_hueco_si_otro_sillon_esta_libre() -> None:
    chairs = [ChairRules(SILLON_A, (regla(),)), ChairRules(SILLON_B, (regla(),))]

    assert at(10) in libres(chairs, blocks=[Scoped(SILLON_A, at(10), at(10, 30))])


def test_nada_antes_de_now() -> None:
    chairs = [ChairRules(SILLON_A, (regla(),))]

    assert libres(chairs, now=at(10, 15)) == [at(10, 30), at(11), at(11, 30)]


def test_solo_el_rango_pedido() -> None:
    chairs = [ChairRules(SILLON_A, (regla(),))]

    assert libres(chairs, desde=at(10), hasta=at(11)) == [at(10), at(10, 30)]


def test_otro_dia_de_la_semana_no_ofrece_nada() -> None:
    chairs = [ChairRules(SILLON_A, (regla(weekday=1),))]

    assert libres(chairs) == []


def test_cap_limita_la_cantidad_devuelta_en_orden() -> None:
    chairs = [ChairRules(SILLON_A, (regla(),))]

    assert libres(chairs, cap=2) == [at(9), at(9, 30)]


def test_reglas_con_duraciones_distintas_en_el_mismo_sillon() -> None:
    chairs = [
        ChairRules(
            SILLON_A,
            (regla(end=time(10), slot=30), regla(start=time(14), end=time(15), slot=60)),
        )
    ]

    assert libres(chairs) == [at(9), at(9, 30), at(14)]


def test_salto_de_horario_omite_la_hora_inexistente() -> None:
    """Domingo 2030-03-10 en Nueva York: 02:00-03:00 local no existe."""
    chairs = [ChairRules(SILLON_A, (regla(start=time(1), end=time(4), weekday=6),))]
    dia = datetime(2030, 3, 10, 0, 0, tzinfo=NY)

    res = libres(
        chairs, desde=dia, hasta=dia + timedelta(days=1), now=dia - timedelta(days=1), tz=NY
    )

    assert [h.astimezone(UTC) for h in res] == [
        datetime(2030, 3, 10, 6, 0, tzinfo=UTC),
        datetime(2030, 3, 10, 6, 30, tzinfo=UTC),
        datetime(2030, 3, 10, 7, 0, tzinfo=UTC),
        datetime(2030, 3, 10, 7, 30, tzinfo=UTC),
    ]


# ------------------------------------------------------------ chairs_on_grid


def test_chairs_on_grid_devuelve_los_sillones_cuya_grilla_contiene_el_inicio_en_orden_de_id() -> (
    None
):
    chairs = [ChairRules(SILLON_B, (regla(),)), ChairRules(SILLON_A, (regla(),))]

    assert chairs_on_grid(chairs, at(10), BA, AHORA) == [SILLON_A, SILLON_B]


def test_chairs_on_grid_descarta_inicio_fuera_de_grilla_u_horario() -> None:
    chairs = [ChairRules(SILLON_A, (regla(),))]

    assert chairs_on_grid(chairs, at(9, 10), BA, AHORA) == []
    assert chairs_on_grid(chairs, at(12), BA, AHORA) == []
    assert chairs_on_grid(chairs, at(8), BA, AHORA) == []


def test_chairs_on_grid_solo_incluye_el_sillon_que_genera_ese_inicio() -> None:
    chairs = [
        ChairRules(SILLON_A, (regla(slot=30),)),
        ChairRules(SILLON_B, (regla(slot=45),)),
    ]

    assert chairs_on_grid(chairs, at(9, 30), BA, AHORA) == [SILLON_A]
    assert chairs_on_grid(chairs, at(9, 45), BA, AHORA) == [SILLON_B]
