/**
 * Cliente API tipado (D2). Borde frontend → backend sin `any` (regla 5).
 *
 * - El access token sale de memoria (`getAccess`), nunca de storage (regla 10).
 * - Ante `401` de un endpoint autenticado renueva UNA vez vía `refresh` (que la
 *   sesión hace single-flight entre pestañas) y reintenta UNA vez.
 * - Si la renovación falla, avisa con `onUnauthorized` para cerrar la sesión.
 * - Los errores son `ApiError {status, detail, extra}`; `extra` lleva las claves
 *   públicas del cuerpo (`conflicts`, `alternatives`, `blocks`, ...).
 */

// Origen del backend; vacío = mismo origen (proxy de Vite / nginx).
const API_ORIGIN: string = (import.meta.env.VITE_API_ORIGIN as string | undefined) ?? "";

export type QueryValue = string | number | boolean | null | undefined;
export type Query = Record<string, QueryValue | readonly QueryValue[]>;

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  query?: Query;
  /** `false` para login/refresh/logout: no manda bearer ni renueva. */
  auth?: boolean;
  /** Token explícito (uso interno de la sesión): se manda tal cual y no renueva. */
  accessToken?: string;
}

export interface ApiClientDeps {
  getAccess: () => string | null;
  refresh: () => Promise<string | null>;
  onUnauthorized: () => void;
}

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly extra: Record<string, unknown>;
  readonly retryAfterSeconds: number | null;

  constructor(
    status: number,
    detail: string,
    extra: Record<string, unknown> = {},
    retryAfterSeconds: number | null = null
  ) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.extra = extra;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

const RENEWABLE = new Set(["token_expired", "token_invalid", "invalid_session"]);

const SIN_SESION: ApiClientDeps = {
  getAccess: () => null,
  refresh: async () => null,
  onUnauthorized: () => undefined
};

let deps: ApiClientDeps = SIN_SESION;

export function configureApi(next: ApiClientDeps): void {
  deps = next;
}

export function resetApiConfig(): void {
  deps = SIN_SESION;
}

function buildUrl(path: string, query?: Query): string {
  const base =
    API_ORIGIN || (typeof window !== "undefined" ? window.location.origin : "http://localhost");
  const url = new URL(path, base);
  for (const [clave, valor] of Object.entries(query ?? {})) {
    const valores = Array.isArray(valor) ? valor : [valor];
    for (const v of valores) {
      if (v !== undefined && v !== null && v !== "") {
        url.searchParams.append(clave, String(v));
      }
    }
  }
  return url.toString();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

async function toApiError(response: Response): Promise<ApiError> {
  let cuerpo: unknown = null;
  try {
    cuerpo = await response.json();
  } catch {
    cuerpo = null;
  }
  const retry = Number(response.headers.get("Retry-After"));
  const retryAfter = Number.isFinite(retry) && retry > 0 ? retry : null;
  if (!isRecord(cuerpo)) {
    return new ApiError(response.status, `http_${response.status}`, {}, retryAfter);
  }
  const { detail, ...extra } = cuerpo;
  // Los 422 de Pydantic traen una lista: se resume sin exponer el input (regla 13).
  const codigo = typeof detail === "string" ? detail : "validation_error";
  return new ApiError(response.status, codigo, extra, retryAfter);
}

async function send(path: string, options: RequestOptions, token: string | null): Promise<Response> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (token !== null && (options.auth !== false || options.accessToken !== undefined)) {
    headers.Authorization = `Bearer ${token}`;
  }
  try {
    return await fetch(buildUrl(path, options.query), {
      method: options.method ?? "GET",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      credentials: "include"
    });
  } catch {
    throw new ApiError(0, "network_error");
  }
}

async function parse<T>(response: Response): Promise<T> {
  if (response.status === 204) {
    return undefined as T;
  }
  const cuerpo: unknown = await response.json();
  return cuerpo as T;
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  if (options.accessToken !== undefined) {
    const directa = await send(path, options, options.accessToken);
    if (directa.ok) {
      return parse<T>(directa);
    }
    throw await toApiError(directa);
  }
  const autenticado = options.auth !== false;
  const primera = await send(path, options, autenticado ? deps.getAccess() : null);
  if (primera.ok) {
    return parse<T>(primera);
  }
  if (primera.status !== 401 || !autenticado) {
    throw await toApiError(primera);
  }
  const error = await toApiError(primera);
  // Solo un access vencido/inválido justifica renovar (p. ej. `invalid_credentials` en
  // el cambio de contraseña es un 401 de dominio, no de sesión).
  if (!RENEWABLE.has(error.detail)) {
    throw error;
  }
  const nuevo = await deps.refresh();
  if (nuevo === null) {
    deps.onUnauthorized();
    throw error;
  }
  const segunda = await send(path, options, nuevo);
  if (segunda.ok) {
    return parse<T>(segunda);
  }
  throw await toApiError(segunda);
}
