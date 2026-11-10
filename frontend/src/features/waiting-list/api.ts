/**
 * Cliente y lecturas de la lista de espera para el personal (C-12, D11/D12).
 * Cola paginada por cursor con "Cargar más"; ofertas refrescadas como la agenda (30 s).
 */
import {
  useInfiniteQuery,
  useQuery,
  type UseInfiniteQueryResult,
  type InfiniteData,
  type UseQueryResult
} from "@tanstack/react-query";
import { apiFetch, type Query } from "../../shared/api/client";
import { AGENDA_REFETCH_MS } from "../../shared/api/queries";
import type {
  AcceptedOffer,
  EntryCreate,
  EntryUpdate,
  ManualOfferCreate,
  Page,
  SlotList,
  WaitingListEntry,
  WaitingListStatus,
  WaitlistOffer,
  WaitlistOfferStatus
} from "../../shared/api/types";

const BASE = "/api/waiting-list";
export const PAGE_SIZE = 50;

export const waitlistKeys = {
  all: ["waiting-list"] as const,
  entries: (filters: QueueFilters) => ["waiting-list", "entries", filters] as const,
  offers: (statuses: readonly WaitlistOfferStatus[]) => ["waiting-list", "offers", statuses] as const,
  slots: (entryId: string, from: string) => ["waiting-list", "slots", entryId, from] as const
};

export interface QueueFilters {
  status: WaitingListStatus[];
  professionalId: string | null;
  from: string | null;
  to: string | null;
}

function queueQuery(filters: QueueFilters, cursor: string | null): Query {
  return {
    status: filters.status,
    professional_id: filters.professionalId ?? undefined,
    from: filters.from ?? undefined,
    to: filters.to ?? undefined,
    limit: PAGE_SIZE,
    cursor: cursor ?? undefined
  };
}

export function useQueue(
  filters: QueueFilters
): UseInfiniteQueryResult<InfiniteData<Page<WaitingListEntry>>> {
  return useInfiniteQuery({
    queryKey: waitlistKeys.entries(filters),
    queryFn: ({ pageParam }) =>
      apiFetch<Page<WaitingListEntry>>(BASE, { query: queueQuery(filters, pageParam) }),
    initialPageParam: null as string | null,
    getNextPageParam: (ultima) => ultima.next_cursor,
    refetchInterval: AGENDA_REFETCH_MS
  });
}

export function useOffers(
  statuses: readonly WaitlistOfferStatus[],
  enabled: boolean
): UseQueryResult<WaitlistOffer[]> {
  return useQuery({
    queryKey: waitlistKeys.offers(statuses),
    queryFn: async () =>
      (
        await apiFetch<Page<WaitlistOffer>>(`${BASE}/offers`, {
          query: { status: [...statuses], limit: 200 }
        })
      ).items,
    enabled,
    refetchInterval: AGENDA_REFETCH_MS
  });
}

export function useSlots(
  entryId: string,
  range: { from: Date; to: Date }
): UseQueryResult<SlotList> {
  return useQuery({
    queryKey: waitlistKeys.slots(entryId, range.from.toISOString()),
    queryFn: () =>
      apiFetch<SlotList>(`${BASE}/${entryId}/slots`, {
        query: { from: range.from.toISOString(), to: range.to.toISOString() }
      })
  });
}

export function createEntry(body: EntryCreate): Promise<WaitingListEntry> {
  return apiFetch<WaitingListEntry>(BASE, { method: "POST", body });
}

export function updateEntry(id: string, body: EntryUpdate): Promise<WaitingListEntry> {
  return apiFetch<WaitingListEntry>(`${BASE}/${id}`, { method: "PATCH", body });
}

export function withdrawEntry(id: string): Promise<WaitingListEntry> {
  return apiFetch<WaitingListEntry>(`${BASE}/${id}/withdraw`, { method: "POST" });
}

export function prioritizeEntry(id: string, reason: string): Promise<WaitingListEntry> {
  return apiFetch<WaitingListEntry>(`${BASE}/${id}/priority`, { method: "POST", body: { reason } });
}

export function unprioritizeEntry(id: string): Promise<WaitingListEntry> {
  return apiFetch<WaitingListEntry>(`${BASE}/${id}/priority`, { method: "DELETE" });
}

export function offerSlot(id: string, body: ManualOfferCreate): Promise<WaitlistOffer> {
  return apiFetch<WaitlistOffer>(`${BASE}/${id}/offers`, { method: "POST", body });
}

export function acceptOffer(id: string): Promise<AcceptedOffer> {
  return apiFetch<AcceptedOffer>(`${BASE}/offers/${id}/accept`, { method: "POST" });
}

export function declineOffer(id: string): Promise<WaitlistOffer> {
  return apiFetch<WaitlistOffer>(`${BASE}/offers/${id}/decline`, { method: "POST" });
}

export function cancelOffer(id: string): Promise<WaitlistOffer> {
  return apiFetch<WaitlistOffer>(`${BASE}/offers/${id}/cancel`, { method: "POST" });
}
