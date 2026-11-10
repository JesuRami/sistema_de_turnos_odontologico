/** Datos sintéticos y handlers MSW de la lista de espera (C-12; regla 13). */
import { http, HttpResponse, type HttpHandler } from "msw";
import type { WaitingListEntry, WaitlistOffer } from "../shared/api/types";
import { agendaHandlers } from "./fixtures";

export function entry(overrides: Partial<WaitingListEntry> = {}): WaitingListEntry {
  return {
    id: "entry-1",
    status: "waiting",
    source: "reception",
    patient: {
      id: "pat-1",
      full_name: "Lucía Espera Ficticia",
      phone_e164: "+5491155550101",
      email: "lucia.espera@example.com"
    },
    professional_id: "prof-1",
    date_from: "2030-01-07",
    date_to: "2030-01-20",
    time_from: null,
    time_to: null,
    weekdays: null,
    notes: null,
    prioritized_at: null,
    priority_reason: null,
    consecutive_expired: 0,
    closed_reason: null,
    created_at: "2030-01-05T13:00:00Z",
    pending_offer: null,
    ...overrides
  };
}

export function offer(overrides: Partial<WaitlistOffer> = {}): WaitlistOffer {
  return {
    id: "offer-1",
    entry_id: "entry-1",
    professional_id: "prof-1",
    chair_id: "chair-1",
    starts_at: "2030-01-09T13:00:00Z",
    ends_at: "2030-01-09T13:30:00Z",
    expires_at: "2030-01-07T15:00:00Z",
    status: "pending",
    mode: "auto",
    appointment_id: null,
    closed_reason: null,
    responded_at: null,
    created_at: "2030-01-07T11:00:00Z",
    ...overrides
  };
}

export interface WaitlistData {
  entries?: WaitingListEntry[];
  offers?: WaitlistOffer[];
}

/** Agenda base + cola y ofertas de solo lectura. */
export function waitlistHandlers(data: WaitlistData = {}): HttpHandler[] {
  return [
    ...agendaHandlers(),
    http.get("/api/waiting-list", () =>
      HttpResponse.json({ items: data.entries ?? [], next_cursor: null })
    ),
    http.get("/api/waiting-list/offers", () =>
      HttpResponse.json({ items: data.offers ?? [], next_cursor: null })
    )
  ];
}
