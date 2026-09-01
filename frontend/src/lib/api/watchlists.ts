/**
 * Typed client for `/api/internal/watchlists*` (docs/API.md §5, roadmap
 * slice 037). Shapes mirror the payloads
 * `backend/src/flightsite/api/internal.py` builds from
 * `flightsite.watchlists.model.WatchlistRecord` /
 * `WatchlistEntryRecord` — see that module's `_watchlist_payload` /
 * `_entry_payload`.
 */
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";

/** The five reference kinds SPEC §42 lists, spelled exactly as
 * `flightsite.watchlists.vocabulary.WatchlistEntryKind` does. */
export type WatchlistEntryKind =
  "icao24" | "registration" | "type_code" | "operator" | "category";

export interface Watchlist {
  id: number;
  name: string;
  description: string | null;
  created_at: string;
  /** How many entries this watchlist currently has. */
  entry_count: number;
}

export interface WatchlistEntry {
  id: number;
  watchlist_id: number;
  kind: WatchlistEntryKind;
  /** Already normalized for `kind` by the backend (lower-case `icao24`,
   * upper-case `registration`/`type_code`/`operator`, the mission-category
   * spelling for `category`) — see `flightsite.watchlists.vocabulary`. */
  value: string;
  note: string | null;
  created_at: string;
}

export interface WatchlistsListResponse {
  watchlists: Watchlist[];
}

export interface WatchlistEntriesResponse {
  entries: WatchlistEntry[];
}

export interface WatchlistCreateInput {
  name: string;
  description?: string | null;
}

export interface WatchlistUpdateInput {
  name: string;
  description?: string | null;
}

export interface WatchlistEntryCreateInput {
  kind: WatchlistEntryKind;
  value: string;
  note?: string | null;
}

const WATCHLISTS_PATH = "/api/internal/watchlists";

function entriesPath(watchlistId: number): string {
  return `${WATCHLISTS_PATH}/${watchlistId}/entries`;
}

const JSON_HEADERS = { "Content-Type": "application/json" };

export function getWatchlists(): Promise<WatchlistsListResponse> {
  return apiFetch<WatchlistsListResponse>(WATCHLISTS_PATH);
}

export function createWatchlist(
  input: WatchlistCreateInput,
): Promise<Watchlist> {
  return apiFetch<Watchlist>(WATCHLISTS_PATH, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(input),
  });
}

export function updateWatchlist(
  watchlistId: number,
  input: WatchlistUpdateInput,
): Promise<Watchlist> {
  return apiFetch<Watchlist>(`${WATCHLISTS_PATH}/${watchlistId}`, {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify(input),
  });
}

export function deleteWatchlist(watchlistId: number): Promise<void> {
  return apiFetch<void>(`${WATCHLISTS_PATH}/${watchlistId}`, {
    method: "DELETE",
  });
}

export function getWatchlistEntries(
  watchlistId: number,
): Promise<WatchlistEntriesResponse> {
  return apiFetch<WatchlistEntriesResponse>(entriesPath(watchlistId));
}

export function addWatchlistEntry(
  watchlistId: number,
  input: WatchlistEntryCreateInput,
): Promise<WatchlistEntry> {
  return apiFetch<WatchlistEntry>(entriesPath(watchlistId), {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(input),
  });
}

export function removeWatchlistEntry(
  watchlistId: number,
  entryId: number,
): Promise<void> {
  return apiFetch<void>(`${entriesPath(watchlistId)}/${entryId}`, {
    method: "DELETE",
  });
}

/** Query key for the watchlist list — every watchlist plus its entry count. */
export const watchlistsQueryKey = ["watchlists"] as const;

/** Query key namespace for one watchlist's entries. */
export const watchlistEntriesQueryKey = (watchlistId: number) =>
  ["watchlists", watchlistId, "entries"] as const;

export function useWatchlistsQuery(): UseQueryResult<WatchlistsListResponse> {
  return useQuery({ queryKey: watchlistsQueryKey, queryFn: getWatchlists });
}

/** One watchlist's entries. `enabled: false` while `watchlistId` is `null`
 * (nothing expanded yet), so collapsing every watchlist card fires no
 * request. */
export function useWatchlistEntriesQuery(
  watchlistId: number | null,
): UseQueryResult<WatchlistEntriesResponse> {
  return useQuery({
    queryKey: watchlistEntriesQueryKey(watchlistId ?? -1),
    queryFn: () => getWatchlistEntries(watchlistId as number),
    enabled: watchlistId !== null,
  });
}

/** Every mutation below invalidates the watchlist list — its `entry_count`
 * can change from an entry mutation, and its `name`/`entry_count` can change
 * from a watchlist mutation — so no consumer of {@link useWatchlistsQuery}
 * has to remember to refetch itself. */
function invalidateWatchlists(
  queryClient: ReturnType<typeof useQueryClient>,
  watchlistId?: number,
): void {
  void queryClient.invalidateQueries({ queryKey: watchlistsQueryKey });
  if (watchlistId !== undefined) {
    void queryClient.invalidateQueries({
      queryKey: watchlistEntriesQueryKey(watchlistId),
    });
  }
}

export function useCreateWatchlistMutation(): UseMutationResult<
  Watchlist,
  Error,
  WatchlistCreateInput
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createWatchlist,
    onSuccess: () => {
      invalidateWatchlists(queryClient);
    },
  });
}

export function useUpdateWatchlistMutation(): UseMutationResult<
  Watchlist,
  Error,
  { watchlistId: number; input: WatchlistUpdateInput }
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ watchlistId, input }) => updateWatchlist(watchlistId, input),
    onSuccess: () => {
      invalidateWatchlists(queryClient);
    },
  });
}

export function useDeleteWatchlistMutation(): UseMutationResult<
  void,
  Error,
  number
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteWatchlist,
    onSuccess: () => {
      invalidateWatchlists(queryClient);
    },
  });
}

export function useAddWatchlistEntryMutation(): UseMutationResult<
  WatchlistEntry,
  Error,
  { watchlistId: number; input: WatchlistEntryCreateInput }
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ watchlistId, input }) =>
      addWatchlistEntry(watchlistId, input),
    onSuccess: (_data, { watchlistId }) => {
      invalidateWatchlists(queryClient, watchlistId);
    },
  });
}

export function useRemoveWatchlistEntryMutation(): UseMutationResult<
  void,
  Error,
  { watchlistId: number; entryId: number }
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ watchlistId, entryId }) =>
      removeWatchlistEntry(watchlistId, entryId),
    onSuccess: (_data, { watchlistId }) => {
      invalidateWatchlists(queryClient, watchlistId);
    },
  });
}
