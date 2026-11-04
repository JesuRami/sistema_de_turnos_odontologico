/**
 * Cliente de la reserva pública (C-07). Anónimo: `credentials: "omit"` (sin cookies ni
 * bearer) y sin renovación de sesión, a diferencia de `apiFetch`. Los errores son `ApiError`
 * con `extra` (p. ej. `alternatives`) y `retryAfterSeconds` para el 429.
 */
import { ApiError, buildUrl, toApiError } from "../../shared/api/client";
import type { BookingAvailability, BookingCatalog, BookingRequest, BookingResult } from "./types";

interface PublicRequest {
  method?: "GET" | "POST";
  body?: unknown;
  query?: Record<string, string>;
}

async function publicFetch<T>(path: string, options: PublicRequest = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.query), {
      method: options.method ?? "GET",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      credentials: "omit"
    });
  } catch {
    throw new ApiError(0, "network_error");
  }
  if (!response.ok) {
    throw await toApiError(response);
  }
  return (await response.json()) as T;
}

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
