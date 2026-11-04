/**
 * Copy de los errores públicos de la reserva (C-07). Voz activa, explica qué pasó y qué hacer;
 * nunca interpola datos del paciente (regla 13).
 */
import { ApiError } from "../../shared/api/client";
import type { BookingSlot } from "./types";

export type BookingField = "name" | "phone" | "email" | "optin" | "privacy";

export interface BookingProblem {
  message: string;
  fields: readonly BookingField[];
  /** Horarios alternativos del `409` (solo inicio, fin y profesional). */
  alternatives: readonly BookingSlot[];
  /** El horario elegido ya no sirve: ofrecer volver a elegir. */
  slotLost: boolean;
}

export const OPT_IN_MESSAGE =
  "Para usar tu teléfono aceptá los avisos por WhatsApp o dejanos un email";
export const LINK_UNAVAILABLE = "Este link de reserva no está disponible";

const GENERIC = "No pudimos completar la reserva. Probá de nuevo en unos minutos";

function minutesText(seconds: number | null): string {
  if (seconds === null) {
    return "unos minutos";
  }
  const minutos = Math.max(1, Math.ceil(seconds / 60));
  return minutos === 1 ? "1 minuto" : `${minutos} minutos`;
}

function isSlot(value: unknown): value is BookingSlot {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const v = value as Record<string, unknown>;
  return (
    typeof v.starts_at === "string" &&
    typeof v.ends_at === "string" &&
    typeof v.professional_id === "string"
  );
}

function alternativesOf(error: ApiError): BookingSlot[] {
  const crudas = error.extra.alternatives;
  return Array.isArray(crudas) ? crudas.filter(isSlot) : [];
}

function problem(message: string, extra: Partial<BookingProblem> = {}): BookingProblem {
  return { message, fields: [], alternatives: [], slotLost: false, ...extra };
}

export function describeProblem(error: unknown): BookingProblem {
  if (!(error instanceof ApiError)) {
    return problem(GENERIC);
  }
  switch (error.detail) {
    case "slot_taken":
      return problem("Ese horario se acaba de ocupar", {
        alternatives: alternativesOf(error),
        slotLost: true
      });
    case "slot_not_offered":
    case "appointment_in_past":
      return problem("Ese horario ya no está disponible. Elegí otro", { slotLost: true });
    case "contact_required":
      return problem("Revisá tu teléfono o tu email: necesitamos al menos uno válido", {
        fields: ["phone", "email"]
      });
    case "whatsapp_opt_in_required":
      return problem(OPT_IN_MESSAGE, { fields: ["phone", "optin"] });
    case "privacy_consent_required":
      return problem("Tenés que aceptar la política de privacidad", { fields: ["privacy"] });
    case "invalid_request":
      return problem("Revisá los datos ingresados");
    case "rate_limited":
      return problem(
        `Hiciste muchos intentos desde esta conexión. Probá de nuevo en ${minutesText(error.retryAfterSeconds)}`
      );
    case "booking_not_found":
      return problem(LINK_UNAVAILABLE);
    case "professional_not_found":
      return problem("Ese profesional ya no está disponible para reservar online");
    case "booking_unavailable":
      return problem(
        "La reserva online no está disponible en este momento. Probá de nuevo en unos minutos o llamá a la clínica"
      );
    case "bot_check_failed":
      return problem("No pudimos verificar la solicitud. Probá de nuevo");
    case "network_error":
      return problem("No hay conexión con el servidor. Revisá tu internet y probá de nuevo");
    default:
      return problem(GENERIC);
  }
}
