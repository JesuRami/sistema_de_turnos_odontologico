/** Cliente de la reserva pública (C-07): anónimo, vía `publicFetch` (sin cookies ni bearer). */
import { publicFetch } from "../../shared/api/public";
import type {
  BookingAvailability,
  BookingCatalog,
  BookingRequest,
  BookingResult,
  WaitlistJoined,
  WaitlistJoinRequest
} from "./types";

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

/** Anotación en la lista de espera de la clínica (C-12, D7). */
export function joinWaitlist(slug: string, request: WaitlistJoinRequest): Promise<WaitlistJoined> {
  return publicFetch<WaitlistJoined>(`${base(slug)}/waiting-list`, { method: "POST", body: request });
}
