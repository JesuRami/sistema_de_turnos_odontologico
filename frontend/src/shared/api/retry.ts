/**
 * Política de reintentos de red (C-14, D11). La usan las queries de TanStack y la cola de
 * reintentos de recepción: se reintenta lo que puede salir bien solo (red caída, 5xx, 429 y la
 * carrera `409 concurrent_update` que la API resuelve con un lock); nunca un 4xx de negocio.
 */
import { ApiError } from "./client";

export const MAX_RETRIES = 3;
const MAX_DELAY_MS = 15_000;
const MAX_RETRY_AFTER_MS = 60_000;
const RETRYABLE_CONFLICTS = new Set(["concurrent_update"]);

/** `true` si repetir el mismo pedido puede funcionar sin que el usuario cambie nada. */
export function isRetryable(error: unknown): boolean {
  if (!(error instanceof ApiError)) {
    return false;
  }
  if (error.status === 0 || error.status === 429) {
    return true;
  }
  if (error.status >= 500) {
    return error.status !== 501;
  }
  return error.status === 409 && RETRYABLE_CONFLICTS.has(error.detail);
}

/** Firma de `retry` de TanStack Query: `failureCount` arranca en 0. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  return failureCount < MAX_RETRIES && isRetryable(error);
}

/** Espera antes del intento `attempt` (0, 1, 2…): `Retry-After` si vino, si no backoff con jitter. */
export function retryDelay(attempt: number, error?: unknown, random: () => number = Math.random): number {
  if (error instanceof ApiError && error.retryAfterSeconds !== null) {
    return Math.min(error.retryAfterSeconds * 1000, MAX_RETRY_AFTER_MS);
  }
  const base = Math.min(1000 * 2 ** attempt, MAX_DELAY_MS);
  return Math.round(base * (0.8 + random() * 0.4));
}
