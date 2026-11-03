import { describe, expect, it } from "vitest";
import { ApiError } from "./client";
import { messageFor } from "./errors";

describe("catálogo de errores", () => {
  it.each([
    ["outside_schedule", "El horario está fuera de la atención del profesional"],
    ["invalid_credentials", "Email o contraseña incorrectos"],
    ["slot_taken", "El horario ya está ocupado"],
    ["overbooking_limit", "Se alcanzó el tope diario de sobreturnos: solo un admin puede excederlo"]
  ])("%s tiene mensaje propio", (detail, mensaje) => {
    expect(messageFor(new ApiError(409, detail))).toBe(mensaje);
  });

  it("un detail desconocido muestra el mensaje genérico", () => {
    expect(messageFor(new ApiError(400, "algo_nuevo"))).toBe(
      "No se pudo completar la operación"
    );
  });

  it("un error que no es de la API también es genérico", () => {
    expect(messageFor(new Error("Ana Prueba +5491155550000"))).toBe(
      "No se pudo completar la operación"
    );
  });

  it("todo detail conocido tiene un mensaje no vacío", () => {
    for (const detail of [
      "slot_blocked",
      "resource_inactive",
      "invalid_transition",
      "appointment_started",
      "attendance_too_early",
      "block_conflicts",
      "patient_duplicate",
      "invalid_merge",
      "schedule_overlap",
      "forbidden_role",
      "network_error"
    ]) {
      expect(messageFor(new ApiError(409, detail))).not.toBe("No se pudo completar la operación");
    }
  });
});
