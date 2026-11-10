import { describe, expect, it } from "vitest";
import {
  containsPersonalData,
  firstError,
  validateDateRange,
  validateEmail,
  validateFreeText,
  validatePhoneAR,
  validateTimeWindow
} from "./validators";

describe("validaciones compartidas (C-14)", () => {
  it.each(["011 15 5555-0123", "+54 9 11 5555-0123", "(0261) 455-0123", ""])("teléfono válido: %s", (tel) => {
    expect(validatePhoneAR(tel)).toBeNull();
  });

  it.each(["12ab", "1234", "011-ABC-0000", "+54 9 11 5555 0123 4567 89"])("teléfono inválido: %s", (tel) => {
    expect(validatePhoneAR(tel)).not.toBeNull();
  });

  it("el mensaje de error nunca repite el valor (regla 13)", () => {
    expect(validatePhoneAR("12ab")).not.toContain("12ab");
    expect(validateEmail("persona@")).not.toContain("persona");
  });

  it.each([
    ["lucia.inventada@example.com", null],
    ["", null],
    ["sin-arroba", "x"],
    ["persona@dominio", "x"]
  ])("email %s", (mail, esperado) => {
    expect(validateEmail(mail) === null).toBe(esperado === null);
  });

  it("detecta datos personales igual que el backend", () => {
    expect(containsPersonalData("Llamar al 11 5555-0123")).toBe(true);
    expect(containsPersonalData("DNI 30.123.456")).toBe(true);
    expect(containsPersonalData("avisar a persona@example.com")).toBe(true);
    expect(containsPersonalData("Prefiere la tarde, 2 hijos")).toBe(false);
    expect(containsPersonalData("Turno 10:30 del 12/03")).toBe(false);
  });

  it("texto libre: opcional, acotado y sin PII", () => {
    expect(validateFreeText("")).toBeNull();
    expect(validateFreeText("Prefiere la tarde")).toBeNull();
    expect(validateFreeText("x".repeat(201))).toBe("Máximo 200 caracteres");
    expect(validateFreeText("corto", { minLength: 10 })).toBe("Escribí al menos 10 caracteres");
    expect(validateFreeText("tel 1155550123")).toBe("No escribas teléfonos, emails ni DNI en este campo");
  });

  it("rangos de fechas y franjas", () => {
    expect(validateDateRange("2030-01-07", "2030-01-07")).toBeNull();
    expect(validateDateRange("2030-01-08", "2030-01-07")).not.toBeNull();
    expect(validateDateRange("", "2030-01-07")).not.toBeNull();
    expect(validateTimeWindow("", "")).toBeNull();
    expect(validateTimeWindow("14:00", "18:00")).toBeNull();
    expect(validateTimeWindow("14:00", "")).not.toBeNull();
    expect(validateTimeWindow("18:00", "14:00")).not.toBeNull();
    expect(firstError(null, "primero", "segundo")).toBe("primero");
  });
});
