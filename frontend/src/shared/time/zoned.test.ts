import { describe, expect, it } from "vitest";
import {
  addDays,
  dateKeyOf,
  formatTime,
  fromZonedWallTime,
  minutesOfDay,
  startOfWeekKey,
  weekdayOf,
  zonedDayRange
} from "./zoned";

const BA = "America/Argentina/Buenos_Aires";
const MADRID = "Europe/Madrid";

describe("fechas en la zona de la clínica", () => {
  it("la hora local de Buenos Aires no depende del navegador en UTC", () => {
    const instante = new Date("2030-01-07T13:00:00Z");
    expect(formatTime(instante, BA)).toBe("10:00");
    expect(dateKeyOf(instante, BA)).toBe("2030-01-07");
    expect(minutesOfDay(instante, BA)).toBe(600);
  });

  it("de noche en UTC ya es otro día que en la clínica", () => {
    const instante = new Date("2030-01-08T01:30:00Z");
    expect(dateKeyOf(instante, BA)).toBe("2030-01-07");
    expect(formatTime(instante, BA)).toBe("22:30");
  });

  it("hora de pared a instante", () => {
    expect(fromZonedWallTime("2030-01-07", "10:00", BA)?.toISOString()).toBe(
      "2030-01-07T13:00:00.000Z"
    );
  });

  it("respeta el cambio de horario de Madrid", () => {
    expect(fromZonedWallTime("2030-03-30", "09:00", MADRID)?.toISOString()).toBe(
      "2030-03-30T08:00:00.000Z"
    );
    expect(fromZonedWallTime("2030-03-31", "09:00", MADRID)?.toISOString()).toBe(
      "2030-03-31T07:00:00.000Z"
    );
    expect(formatTime(new Date("2030-03-31T07:00:00Z"), MADRID)).toBe("09:00");
  });

  it("una hora inexistente por el salto de horario devuelve null", () => {
    expect(fromZonedWallTime("2030-03-31", "02:30", MADRID)).toBeNull();
  });

  it("el rango de un día local cubre 23 horas el día del salto", () => {
    const { from, to } = zonedDayRange("2030-03-31", MADRID);
    expect(from.toISOString()).toBe("2030-03-30T23:00:00.000Z");
    expect(to.toISOString()).toBe("2030-03-31T22:00:00.000Z");
  });

  it("aritmética de días y semanas por calendario", () => {
    expect(addDays("2030-01-31", 1)).toBe("2030-02-01");
    expect(addDays("2030-01-07", -7)).toBe("2029-12-31");
    expect(weekdayOf("2030-01-07")).toBe(0);
    expect(weekdayOf("2030-01-13")).toBe(6);
    expect(startOfWeekKey("2030-01-10")).toBe("2030-01-07");
    expect(startOfWeekKey("2030-01-13")).toBe("2030-01-07");
  });
});
