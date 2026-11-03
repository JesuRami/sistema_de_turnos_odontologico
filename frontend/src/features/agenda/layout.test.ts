import { describe, expect, it } from "vitest";
import { rule } from "../../test/fixtures";
import { colorFor, isPendingSoon, layoutItems, visibleRange } from "./layout";

const TZ = "America/Argentina/Buenos_Aires";
const at = (hhmm: string, day = "07") => new Date(`2030-01-${day}T${hhmm}:00-03:00`);

describe("rango horario visible", () => {
  it("toma el mínimo inicio y el máximo fin de las reglas del día", () => {
    const reglas = [
      rule({ start_time: "09:00:00", end_time: "13:00:00" }),
      rule({ id: "r2", start_time: "14:30:00", end_time: "18:15:00" })
    ];
    expect(visibleRange(reglas, ["2030-01-07"])).toEqual({ startMin: 540, endMin: 1140 });
  });

  it("ignora reglas de otros días, inactivas o fuera de vigencia", () => {
    const reglas = [
      rule({ weekday: 1, start_time: "06:00:00" }),
      rule({ active: false, start_time: "06:00:00" }),
      rule({ valid_to: "2029-12-31", start_time: "06:00:00" }),
      rule({ start_time: "10:00:00", end_time: "12:00:00" })
    ];
    expect(visibleRange(reglas, ["2030-01-07"])).toEqual({ startMin: 600, endMin: 720 });
  });

  it("sin reglas usa 08:00 a 20:00", () => {
    expect(visibleRange([], ["2030-01-07"])).toEqual({ startMin: 480, endMin: 1200 });
  });
});

describe("posiciones en la grilla", () => {
  const rango = { startMin: 540, endMin: 780 };

  it("ubica cada turno por columna y minutos desde el inicio visible", () => {
    const [ubicado] = layoutItems(
      [{ id: "a", start: at("10:00"), end: at("10:30"), column: "chair-1" }],
      rango,
      TZ
    );
    expect(ubicado).toMatchObject({ id: "a", column: "chair-1", top: 60, height: 30, lane: 0, lanes: 1 });
  });

  it("reparte en carriles lo que se solapa en la misma columna", () => {
    const ubicados = layoutItems(
      [
        { id: "a", start: at("10:00"), end: at("10:30"), column: "c" },
        { id: "b", start: at("10:15"), end: at("10:45"), column: "c" },
        { id: "c", start: at("11:00"), end: at("11:30"), column: "c" },
        { id: "d", start: at("10:00"), end: at("10:30"), column: "otra" }
      ],
      rango,
      TZ
    );
    const por = Object.fromEntries(ubicados.map((u) => [u.id, u]));
    expect([por.a?.lane, por.a?.lanes]).toEqual([0, 2]);
    expect([por.b?.lane, por.b?.lanes]).toEqual([1, 2]);
    expect([por.c?.lane, por.c?.lanes]).toEqual([0, 1]);
    expect([por.d?.lane, por.d?.lanes]).toEqual([0, 1]);
  });

  it("recorta lo que sale del rango visible y descarta lo que queda afuera", () => {
    const ubicados = layoutItems(
      [
        { id: "temprano", start: at("08:30"), end: at("09:30"), column: "c" },
        { id: "afuera", start: at("14:00"), end: at("15:00"), column: "c" }
      ],
      rango,
      TZ
    );
    expect(ubicados).toHaveLength(1);
    expect(ubicados[0]).toMatchObject({ id: "temprano", top: 0, height: 30 });
  });
});

describe("distintivos", () => {
  const ahora = new Date("2030-01-07T11:00:00Z");

  it("pendiente que empieza en menos de 24 h", () => {
    expect(isPendingSoon("pending", new Date("2030-01-07T16:00:00Z"), ahora)).toBe(true);
    expect(isPendingSoon("pending", new Date("2030-01-09T16:00:00Z"), ahora)).toBe(false);
    expect(isPendingSoon("confirmed", new Date("2030-01-07T16:00:00Z"), ahora)).toBe(false);
    expect(isPendingSoon("pending", new Date("2030-01-07T10:00:00Z"), ahora)).toBe(false);
  });

  it("color propio o uno estable derivado del id", () => {
    expect(colorFor({ id: "p", color: "#123456" })).toBe("#123456");
    expect(colorFor({ id: "p-1", color: null })).toBe(colorFor({ id: "p-1", color: null }));
    expect(colorFor({ id: "p-1", color: null })).toMatch(/^#[0-9a-f]{6}$/);
  });
});
