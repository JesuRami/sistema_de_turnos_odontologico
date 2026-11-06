/** Lecturas de reportes y auditoría (C-13) y descargas con la sesión del usuario. */
import {
  useInfiniteQuery,
  useQuery,
  type UseInfiniteQueryResult,
  type UseQueryResult,
  type InfiniteData
} from "@tanstack/react-query";
import { apiFetch } from "../../shared/api/client";
import type {
  AbsenteeismReport,
  AppointmentEventKind,
  AuditEvent,
  CancellationsReport,
  OccupancyReport,
  Page,
  ReportGroupBy,
  WhatsAppReport
} from "../../shared/api/types";

export interface DateRange {
  from: string;
  to: string;
}

export interface AuditFilters {
  /** Instantes ISO (inicio del día `from` y fin del día `to` en la zona de la clínica). */
  from: string;
  to: string;
  event: AppointmentEventKind | "";
  appointmentId: string;
}

const AUDIT_LIMIT = 50;

export const reportKeys = {
  all: ["reports"] as const,
  occupancy: (r: DateRange, g: ReportGroupBy) => ["reports", "occupancy", r, g] as const,
  absenteeism: (r: DateRange) => ["reports", "absenteeism", r] as const,
  cancellations: (r: DateRange) => ["reports", "cancellations", r] as const,
  whatsapp: (r: DateRange) => ["reports", "whatsapp", r] as const,
  audit: (f: AuditFilters) => ["reports", "audit", f] as const
};

export function useOccupancy(range: DateRange | null, groupBy: ReportGroupBy): UseQueryResult<OccupancyReport> {
  return useQuery({
    queryKey: range === null ? ["reports", "occupancy", "off"] : reportKeys.occupancy(range, groupBy),
    queryFn: () =>
      apiFetch<OccupancyReport>("/api/reports/occupancy", {
        query: { from: range?.from, to: range?.to, group_by: groupBy }
      }),
    enabled: range !== null
  });
}

export function useAbsenteeism(range: DateRange | null): UseQueryResult<AbsenteeismReport> {
  return useQuery({
    queryKey: range === null ? ["reports", "absenteeism", "off"] : reportKeys.absenteeism(range),
    queryFn: () =>
      apiFetch<AbsenteeismReport>("/api/reports/absenteeism", {
        query: { from: range?.from, to: range?.to }
      }),
    enabled: range !== null
  });
}

export function useCancellations(range: DateRange | null): UseQueryResult<CancellationsReport> {
  return useQuery({
    queryKey: range === null ? ["reports", "cancellations", "off"] : reportKeys.cancellations(range),
    queryFn: () =>
      apiFetch<CancellationsReport>("/api/reports/cancellations", {
        query: { from: range?.from, to: range?.to }
      }),
    enabled: range !== null
  });
}

export function useWhatsAppReport(range: DateRange | null): UseQueryResult<WhatsAppReport> {
  return useQuery({
    queryKey: range === null ? ["reports", "whatsapp", "off"] : reportKeys.whatsapp(range),
    queryFn: () =>
      apiFetch<WhatsAppReport>("/api/reports/whatsapp", {
        query: { from: range?.from, to: range?.to }
      }),
    enabled: range !== null
  });
}

export function useAudit(
  filters: AuditFilters | null
): UseInfiniteQueryResult<InfiniteData<Page<AuditEvent>, string | null>> {
  return useInfiniteQuery({
    queryKey: filters === null ? ["reports", "audit", "off"] : reportKeys.audit(filters),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      apiFetch<Page<AuditEvent>>("/api/audit/appointments", {
        query: {
          from: filters?.from,
          to: filters?.to,
          event: filters?.event,
          appointment_id: filters?.appointmentId,
          limit: AUDIT_LIMIT,
          cursor: pageParam
        }
      }),
    getNextPageParam: (ultima) => ultima.next_cursor,
    enabled: filters !== null
  });
}
