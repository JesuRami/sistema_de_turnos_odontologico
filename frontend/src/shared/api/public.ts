/**
 * Fetch anónimo de las rutas públicas (reserva C-07, gestión por token C-08).
 * `credentials: "omit"`: sin cookies ni bearer, y sin renovación de sesión (a diferencia de
 * `apiFetch`). Los errores son `ApiError` con `extra` (p. ej. `alternatives`) y
 * `retryAfterSeconds` para el 429.
 */
import { ApiError, buildUrl, toApiError } from "./client";

export interface PublicRequest {
  method?: "GET" | "POST" | "PATCH";
  body?: unknown;
  query?: Record<string, string>;
}

export async function publicFetch<T>(path: string, options: PublicRequest = {}): Promise<T> {
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
      credentials: "omit",
      // El token viaja en el path: nunca se filtra por `Referer` (C-08, D2).
      referrerPolicy: "no-referrer"
    });
  } catch {
    throw new ApiError(0, "network_error");
  }
  if (!response.ok) {
    throw await toApiError(response);
  }
  return (await response.json()) as T;
}
