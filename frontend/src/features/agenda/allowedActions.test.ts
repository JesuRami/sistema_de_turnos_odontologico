import { describe, expect, it } from "vitest";
import type { AppointmentStatus, UserRole } from "../../shared/api/types";
import { allowedActions } from "./allowedActions";

const TZ = "America/Argentina/Buenos_Aires";
const INICIO = new Date("2030-01-07T13:00:00Z"); // lunes 10:00 local
const antes = new Date("2030-01-07T11:00:00Z"); // 08:00 del mismo día
const despues = new Date("2030-01-07T13:05:00Z");
const diaAnterior = new Date("2030-01-06T13:00:00Z");

function acciones(role: UserRole, status: AppointmentStatus, now: Date) {
  return allowedActions(role, { status, starts_at: INICIO.toISOString() }, now, TZ);
}

describe("acciones permitidas por rol y estado", () => {
  it("recepción sobre un pendiente futuro: confirmar, reprogramar y cancelar", () => {
    expect(acciones("recepcion", "pending", antes)).toEqual({
      confirm: true,
      reschedule: true,
      cancel: true,
      present: false,
      absent: false,
      noShow: false
    });
  });

  it("presente desde el día del turno; ausente y no-show desde la hora", () => {
    expect(acciones("recepcion", "confirmed", antes)).toMatchObject({
      present: true,
      absent: false,
      noShow: false
    });
    expect(acciones("recepcion", "confirmed", despues)).toMatchObject({
      present: true,
      absent: true,
      noShow: true,
      cancel: false,
      reschedule: false
    });
    expect(acciones("recepcion", "confirmed", diaAnterior)).toMatchObject({ present: false });
  });

  it("el odontólogo solo marca asistencia", () => {
    expect(acciones("odontologo", "confirmed", despues)).toEqual({
      confirm: false,
      reschedule: false,
      cancel: false,
      present: true,
      absent: true,
      noShow: true
    });
    expect(acciones("odontologo", "pending", antes)).toEqual({
      confirm: false,
      reschedule: false,
      cancel: false,
      present: false,
      absent: false,
      noShow: false
    });
  });

  it.each(["cancelled", "absent", "no_show", "present"] as const)(
    "un turno %s no admite acciones",
    (estado) => {
      expect(Object.values(acciones("admin", estado, antes)).some(Boolean)).toBe(false);
    }
  );
});
