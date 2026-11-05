/** Lecturas de la gestión por token con TanStack Query (QueryClient propio de la página). */
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { fetchManageAvailability, fetchManageView } from "./api";
import type { ManageAvailability, ManageView } from "./types";

/** Días que se piden para reprogramar (el backend acepta hasta 14). */
export const RESCHEDULE_DAYS = 14;

export function viewKey(token: string): readonly unknown[] {
  return ["manage", token, "view"];
}

export function useManageView(token: string): UseQueryResult<ManageView> {
  return useQuery({
    queryKey: viewKey(token),
    queryFn: () => fetchManageView(token),
    // Un 404/410 no mejora al reintentar.
    retry: false
  });
}

export function useManageAvailability(
  token: string,
  range: { from: Date; to: Date },
  enabled: boolean
): UseQueryResult<ManageAvailability> {
  return useQuery({
    queryKey: ["manage", token, "availability", range.from.toISOString()],
    queryFn: () => fetchManageAvailability(token, range),
    enabled,
    // Los huecos cambian: siempre frescos al volver a mirarlos.
    staleTime: 0
  });
}
