/**
 * Lecturas con TanStack Query (D3). Los rangos se piden completos siguiendo
 * `next_cursor`; las mutaciones invalidan por prefijo de clave.
 */
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { apiFetch, type Query } from "./client";
import type {
  Appointment,
  Block,
  Chair,
  ClinicPolicies,
  ClinicProfile,
  FollowUpPage,
  Page,
  Professional,
  ReminderTimeline,
  ScheduleRule
} from "./types";

export const queryKeys = {
  clinic: ["clinic"] as const,
  professionals: ["professionals"] as const,
  chairs: ["chairs"] as const,
  schedules: ["schedules"] as const,
  policies: ["policies"] as const,
  appointments: ["appointments"] as const,
  blocks: ["blocks"] as const,
  reminders: ["reminders"] as const,
  followUp: ["follow-up"] as const
};

/** Todas las páginas de un listado por cursor. */
export async function fetchAll<T>(path: string, query: Query, limit: number): Promise<T[]> {
  const items: T[] = [];
  let cursor: string | null = null;
  do {
    const pagina: Page<T> = await apiFetch<Page<T>>(path, {
      query: { ...query, limit, cursor: cursor ?? undefined }
    });
    items.push(...pagina.items);
    cursor = pagina.next_cursor;
  } while (cursor !== null);
  return items;
}

export function useClinic(): UseQueryResult<ClinicProfile> {
  return useQuery({
    queryKey: queryKeys.clinic,
    queryFn: () => apiFetch<ClinicProfile>("/api/clinic"),
    staleTime: Infinity
  });
}

export function useProfessionals(): UseQueryResult<Professional[]> {
  return useQuery({
    queryKey: queryKeys.professionals,
    queryFn: () => fetchAll<Professional>("/api/professionals", {}, 200)
  });
}

export function useChairs(): UseQueryResult<Chair[]> {
  return useQuery({
    queryKey: queryKeys.chairs,
    queryFn: () => fetchAll<Chair>("/api/chairs", {}, 200)
  });
}

export function useSchedules(): UseQueryResult<ScheduleRule[]> {
  return useQuery({
    queryKey: queryKeys.schedules,
    queryFn: () => fetchAll<ScheduleRule>("/api/schedules", {}, 200)
  });
}

export function usePolicies(enabled = true): UseQueryResult<ClinicPolicies> {
  return useQuery({
    queryKey: queryKeys.policies,
    queryFn: () => apiFetch<ClinicPolicies>("/api/clinic/policies"),
    enabled
  });
}

/**
 * Intervalo de refresco de la agenda (C-07, D13): una reserva online aparece sin recargar.
 * Con la pestaña oculta TanStack no refresca (`refetchIntervalInBackground` queda en false).
 */
export const AGENDA_REFETCH_MS = 30_000;

export function useAppointments(range: { from: Date; to: Date } | null): UseQueryResult<Appointment[]> {
  return useQuery({
    queryKey: [...queryKeys.appointments, range?.from.toISOString(), range?.to.toISOString()],
    queryFn: () =>
      fetchAll<Appointment>(
        "/api/appointments",
        { from: range?.from.toISOString(), to: range?.to.toISOString() },
        500
      ),
    enabled: range !== null,
    refetchInterval: AGENDA_REFETCH_MS
  });
}

export function useBlocks(range: { from: Date; to: Date } | null): UseQueryResult<Block[]> {
  return useQuery({
    queryKey: [...queryKeys.blocks, range?.from.toISOString(), range?.to.toISOString()],
    queryFn: () =>
      fetchAll<Block>(
        "/api/blocks",
        { from: range?.from.toISOString(), to: range?.to.toISOString() },
        200
      ),
    enabled: range !== null
  });
}

/** Timeline de recordatorios de un turno (C-11, D3). */
export function useReminderTimeline(appointmentId: string): UseQueryResult<ReminderTimeline> {
  return useQuery({
    queryKey: [...queryKeys.reminders, appointmentId],
    queryFn: () => apiFetch<ReminderTimeline>(`/api/appointments/${appointmentId}/reminders`)
  });
}

/**
 * Seguimiento del rango visible (C-11, D8): todas las páginas, con los totales de la primera.
 * Se refresca con el mismo intervalo que la agenda; solo lo pide admin/recepción.
 */
export function useFollowUp(
  range: { from: Date; to: Date } | null,
  enabled: boolean
): UseQueryResult<FollowUpPage> {
  return useQuery({
    queryKey: [...queryKeys.followUp, range?.from.toISOString(), range?.to.toISOString()],
    queryFn: async () => {
      let cursor: string | null = null;
      let primera: FollowUpPage | null = null;
      const items: FollowUpPage["items"] = [];
      do {
        const pagina: FollowUpPage = await apiFetch<FollowUpPage>("/api/reminders/follow-up", {
          query: {
            from: range?.from.toISOString(),
            to: range?.to.toISOString(),
            limit: 200,
            cursor: cursor ?? undefined
          }
        });
        primera = primera ?? pagina;
        items.push(...pagina.items);
        cursor = pagina.next_cursor;
      } while (cursor !== null);
      return { items, next_cursor: null, totals: primera.totals };
    },
    enabled: enabled && range !== null,
    refetchInterval: AGENDA_REFETCH_MS
  });
}
