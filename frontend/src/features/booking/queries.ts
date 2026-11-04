/** Lecturas públicas con TanStack Query (D12): catálogo y disponibilidad por ventana de 14 días. */
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { addDays, zonedRange, type DateKey } from "../../shared/time/zoned";
import { fetchAvailability, fetchCatalog } from "./api";
import type { BookingAvailability, BookingCatalog } from "./types";

/** Días por ventana (el backend acepta hasta 14). */
export const WINDOW_DAYS = 14;
/** Ventanas navegables: 4 × 14 = 56 días, dentro del horizonte de 60. */
export const WINDOWS = 4;

export function windowRange(
  today: DateKey,
  index: number,
  tz: string
): { from: Date; to: Date } {
  return zonedRange(addDays(today, WINDOW_DAYS * index), WINDOW_DAYS, tz);
}

export function catalogKey(slug: string): readonly unknown[] {
  return ["booking", slug, "catalog"];
}

export function availabilityKey(
  slug: string,
  professionalId: string,
  from: Date
): readonly unknown[] {
  return ["booking", slug, "availability", professionalId, from.toISOString()];
}

export function useCatalog(slug: string): UseQueryResult<BookingCatalog> {
  return useQuery({
    queryKey: catalogKey(slug),
    queryFn: () => fetchCatalog(slug),
    // Un 404 no mejora al reintentar.
    retry: false
  });
}

export function useAvailability(
  slug: string,
  professionalId: string | null,
  range: { from: Date; to: Date }
): UseQueryResult<BookingAvailability> {
  return useQuery({
    queryKey: availabilityKey(slug, professionalId ?? "", range.from),
    queryFn: () => fetchAvailability(slug, professionalId ?? "", range),
    enabled: professionalId !== null,
    // La disponibilidad cambia: siempre fresca al volver a mirarla.
    staleTime: 0
  });
}
