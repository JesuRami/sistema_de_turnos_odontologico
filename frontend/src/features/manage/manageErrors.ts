/**
 * Copy de los errores de la gestión por token (C-08). Voz activa: qué pasó y qué hacer. Nunca
 * interpola datos del paciente ni el token (regla 13).
 */
import { ApiError } from "../../shared/api/client";
import type { ExpiredClinic, ManageSlot } from "./types";

export interface ManageProblem {
  message: string;
  /** Mostrar el teléfono de la clínica (derivación). */
  contact: boolean;
  /** Horarios alternativos del `409 slot_taken` (solo inicio y fin). */
  alternatives: readonly ManageSlot[];
  /** El link venció o no existe: se reemplaza toda la página por la de contacto. */
  linkGone: boolean;
  /** Clínica que informa el `410` para la pantalla de contacto. */
  expiredClinic: ExpiredClinic | null;
  /** La vista quedó desactualizada: hay que volver a pedirla. */
  stale: boolean;
}

const GENERIC = "No pudimos completar la acción. Probá de nuevo en unos minutos";

function problem(message: string, extra: Partial<ManageProblem> = {}): ManageProblem {
  return {
    message,
    contact: false,
    alternatives: [],
    linkGone: false,
    expiredClinic: null,
    stale: false,
    ...extra
  };
}

function isSlot(value: unknown): value is ManageSlot {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const v = value as Record<string, unknown>;
  return typeof v.starts_at === "string" && typeof v.ends_at === "string";
}

function expiredClinicOf(error: ApiError): ExpiredClinic | null {
  const clinica = error.extra.clinic;
  if (typeof clinica !== "object" || clinica === null) {
    return null;
  }
  const c = clinica as Record<string, unknown>;
  if (typeof c.name !== "string") {
    return null;
  }
  return { name: c.name, phone: typeof c.phone === "string" ? c.phone : null };
}

function minutesText(seconds: number | null): string {
  if (seconds === null) {
    return "unos minutos";
  }
  const minutos = Math.max(1, Math.ceil(seconds / 60));
  return minutos === 1 ? "1 minuto" : `${minutos} minutos`;
}

export function describeManageProblem(error: unknown, windowHours: number): ManageProblem {
  if (!(error instanceof ApiError)) {
    return problem(GENERIC);
  }
  switch (error.detail) {
    case "manage_link_expired":
    case "manage_link_not_found":
      return problem("Este link ya no está disponible", {
        linkGone: true,
        expiredClinic: expiredClinicOf(error)
      });
    case "cancellation_window_closed":
      return problem(
        `Ya no podés cancelar online: faltan menos de ${windowHours} h para tu turno. Hablá con la clínica`,
        { contact: true, stale: true }
      );
    case "slot_taken": {
      const crudas = error.extra.alternatives;
      return problem("Ese horario se acaba de ocupar", {
        alternatives: Array.isArray(crudas) ? crudas.filter(isSlot) : [],
        stale: true
      });
    }
    case "slot_not_offered":
    case "appointment_in_past":
      return problem("Ese horario ya no está disponible. Elegí otro", { stale: true });
    case "appointment_started":
      return problem("Este turno ya empezó. Si necesitás algo, hablá con la clínica", {
        contact: true,
        stale: true
      });
    case "invalid_transition":
    case "appointment_changed":
      return problem("Tu turno cambió mientras lo mirabas. Revisá cómo quedó", { stale: true });
    case "rate_limited":
      return problem(
        `Hiciste muchos intentos seguidos. Probá de nuevo en ${minutesText(error.retryAfterSeconds)}`
      );
    case "manage_unavailable":
      return problem(
        "La gestión online no está disponible en este momento. Probá en unos minutos o llamá a la clínica",
        { contact: true }
      );
    case "invalid_request":
      return problem("Revisá los datos ingresados");
    default:
      return problem(GENERIC);
  }
}
