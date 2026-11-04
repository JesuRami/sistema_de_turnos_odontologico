/** Datos sintéticos y handlers MSW de la reserva pública (regla 13). */
import { http, HttpResponse, type HttpHandler } from "msw";
import type {
  BookingAvailability,
  BookingCatalog,
  BookingResult,
  BookingSlot
} from "../features/booking/types";

export const SLUG = "clinica-demo";
export const TZ = "America/Argentina/Buenos_Aires";
export const PROF_1 = { id: "prof-1", display_name: "Dra. Ficticia Uno" };
export const PROF_2 = { id: "prof-2", display_name: "Dr. Ficticio Dos" };

export function catalog(overrides: Partial<BookingCatalog> = {}): BookingCatalog {
  return {
    name: "Clínica Demo Ficticia",
    timezone: TZ,
    professionals: [PROF_1, PROF_2],
    ...overrides
  };
}

/** Hueco de 30 min que arranca en `startsAt` (ISO UTC). */
export function slot(startsAt: string, professionalId = PROF_1.id): BookingSlot {
  const fin = new Date(new Date(startsAt).getTime() + 30 * 60_000).toISOString();
  return { starts_at: startsAt, ends_at: fin, professional_id: professionalId };
}

// Lunes 2030-01-07 y martes 08/01 en Buenos Aires (UTC-3): 10:00 local = 13:00Z.
export const LUN_10 = slot("2030-01-07T13:00:00Z");
export const LUN_1030 = slot("2030-01-07T13:30:00Z");
export const MAR_09 = slot("2030-01-08T12:00:00Z");

export function availability(slots: BookingSlot[] = [LUN_10, LUN_1030, MAR_09]): BookingAvailability {
  return { timezone: TZ, slots };
}

export function result(overrides: Partial<BookingResult> = {}): BookingResult {
  return {
    starts_at: LUN_10.starts_at,
    ends_at: LUN_10.ends_at,
    professional_id: PROF_1.id,
    channel: "whatsapp",
    warnings: [],
    manage_url: "http://localhost:5173/g/token-ficticio-0123456789012345678901234567",
    ...overrides
  };
}

export interface BookingData {
  catalog?: BookingCatalog;
  slots?: BookingSlot[];
}

/** Lecturas públicas: catálogo y disponibilidad (sin importar la ventana pedida). */
export function bookingHandlers(data: BookingData = {}): HttpHandler[] {
  return [
    http.get(`/api/booking/${SLUG}`, () => HttpResponse.json(data.catalog ?? catalog())),
    http.get(`/api/booking/${SLUG}/availability`, ({ request }) => {
      const desde = new Date(new URL(request.url).searchParams.get("from") ?? "");
      // Solo la primera ventana trae huecos: las siguientes (prefetch) vienen vacías.
      const primera = desde.getTime() <= new Date("2030-01-07T03:00:00Z").getTime();
      return HttpResponse.json(availability(primera ? (data.slots ?? undefined) : []));
    })
  ];
}
