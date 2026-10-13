/** Cliente API tipado (borde frontend→backend; sin `any` — regla dura 5). */

const API_BASE: string =
  (import.meta.env.VITE_API_URL as string | undefined) ?? "/api";

interface HealthResponse {
  status: string;
}

interface ApiError {
  detail: string;
}

async function request<T>(path: string): Promise<T> {
  const response: Response = await fetch(`${API_BASE}${path}`);
  const body: unknown = await response.json();
  if (!response.ok) {
    const error = body as ApiError;
    throw new Error(error.detail ?? `API ${response.status}`);
  }
  return body as T;
}

export async function fetchHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/health");
}
