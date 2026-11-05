/** Cliente de la reserva pública (C-07): anónimo, vía `publicFetch` (sin cookies ni bearer). */
import { publicFetch } from "../../shared/api/public";
import type { BookingAvailability, BookingCatalog, BookingRequest, BookingResult } from "./types";

const base = (slug: string): string => `/api/booking/${encodeURIComponent(slug)}`;

export function fetchCatalog(slug: string): Promise<BookingCatalog> {
  return publicFetch<BookingCatalog>(base(slug));
}

export function fetchAvailability(
  slug: string,
  professionalId: string,
  range: { from: Date; to: Date }
): Promise<BookingAvailability> {
  return publicFetch<BookingAvailability>(`${base(slug)}/availability`, {
    query: {
      professional_id: professionalId,
      from: range.from.toISOString(),
      to: range.to.toISOString()
    }
  });
}

export function createBooking(slug: string, request: BookingRequest): Promise<BookingResult> {
  return publicFetch<BookingResult>(`${base(slug)}/appointments`, { method: "POST", body: request });
}
