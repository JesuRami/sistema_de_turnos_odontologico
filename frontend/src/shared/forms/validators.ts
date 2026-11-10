/**
 * Validaciones de formulario compartidas (C-14, D11). Espejo de las reglas del backend para avisar
 * antes de enviar; la API sigue siendo la autoridad. Los mensajes nunca repiten el valor (regla 13).
 */

export type Validation = string | null;

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
// Igual que `app/common/free_text.py`: email, o tramos de dígitos con separadores de teléfono/DNI.
const FREE_TEXT_EMAIL_RE = /[^\s@]+@[^\s@]+\.[^\s@]+/;
const DIGIT_RUN_RE = /\+?\d[\d\s.\-()/]*\d/g;
const PII_MIN_DIGITS = 7;
const PHONE_ALLOWED_RE = /^\+?[\d\s().-]+$/;

export const FREE_TEXT_MAX = 200;

export function validateRequired(value: string, message: string): Validation {
  return value.trim() === "" ? message : null;
}

export function validateEmail(value: string): Validation {
  const v = value.trim();
  if (v === "") {
    return null;
  }
  return EMAIL_RE.test(v) && v.length <= 254 ? null : "Revisá el email: parece incompleto";
}

/** Teléfono argentino con código de área: 8 a 15 dígitos, solo separadores comunes. */
export function validatePhoneAR(value: string): Validation {
  const v = value.trim();
  if (v === "") {
    return null;
  }
  const digitos = v.replace(/\D/g, "").length;
  if (!PHONE_ALLOWED_RE.test(v) || digitos < 8 || digitos > 15) {
    return "Revisá el teléfono: va con código de área, por ejemplo 011 15 5555-0123";
  }
  return null;
}

/** ¿Parece tener un teléfono, un email o un DNI? (misma heurística que el backend). */
export function containsPersonalData(text: string): boolean {
  if (FREE_TEXT_EMAIL_RE.test(text)) {
    return true;
  }
  for (const tramo of text.match(DIGIT_RUN_RE) ?? []) {
    if (tramo.replace(/\D/g, "").length >= PII_MIN_DIGITS) {
      return true;
    }
  }
  return false;
}

/** Nota o motivo operativo: opcional (salvo `minLength`), corto y sin datos personales. */
export function validateFreeText(
  value: string,
  { minLength = 0, maxLength = FREE_TEXT_MAX }: { minLength?: number; maxLength?: number } = {}
): Validation {
  const v = value.trim();
  if (v === "" && minLength === 0) {
    return null;
  }
  if (v.length < minLength) {
    return `Escribí al menos ${minLength} caracteres`;
  }
  if (v.length > maxLength) {
    return `Máximo ${maxLength} caracteres`;
  }
  if (containsPersonalData(v)) {
    return "No escribas teléfonos, emails ni DNI en este campo";
  }
  return null;
}

/** Rango de fechas `YYYY-MM-DD` (inclusive): hasta ≥ desde. */
export function validateDateRange(from: string, to: string): Validation {
  if (from === "" || to === "") {
    return "Completá las dos fechas";
  }
  return to < from ? "La fecha final no puede ser anterior a la inicial" : null;
}

/** Franja horaria `HH:MM` opcional: las dos o ninguna, y hasta > desde. */
export function validateTimeWindow(from: string, to: string): Validation {
  if (from === "" && to === "") {
    return null;
  }
  if (from === "" || to === "") {
    return "Completá la franja desde y hasta, o dejá las dos vacías";
  }
  return to <= from ? "La franja termina antes de empezar" : null;
}

/** Primer error de una lista de validaciones (o `null`). */
export function firstError(...validaciones: Validation[]): Validation {
  return validaciones.find((v) => v !== null) ?? null;
}
