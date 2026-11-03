/** Cliente API tipado (borde frontend→backend; sin `any` — regla dura 5). */

// Origen del backend; vacío = mismo origen (proxy de Vite en dev). Los endpoints de
// dominio viven bajo `${API_ORIGIN}/api/...`; `/health` es infraestructura, fuera de `/api`.
const API_ORIGIN: string = (import.meta.env.VITE_API_ORIGIN as string | undefined) ?? "";

interface HealthResponse {
  status: string;
}

interface ApiError {
  detail: string;
}

async function request<T>(url: string): Promise<T> {
  const response: Response = await fetch(url);
  const body: unknown = await response.json();
  if (!response.ok) {
    const error = body as ApiError;
    throw new Error(error.detail ?? `API ${response.status}`);
  }
  return body as T;
}

export async function fetchHealth(): Promise<HealthResponse> {
  return request<HealthResponse>(`${API_ORIGIN}/health`);
}
