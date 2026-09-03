/**
 * Typed client for `POST`/`GET /api/internal/metadata/*` (docs/API.md §5,
 * roadmap slice 025). The shapes mirror the payloads
 * `backend/src/flightsite/api/internal.py` builds: the trigger endpoint's
 * `{started, already_running, started_ms}` and the status endpoint's one
 * entry per registered source (`mictronics`, `faa` as of slices 022/023).
 */
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";

/** Mirrors the status endpoint's per-source `status` field. `"running"`
 * overrides whatever the last completed attempt recorded — read from the
 * importer's in-flight state, not the durable row. */
export type MetadataSourceStatus = "ok" | "failed" | "never-run" | "running";

/** One registered source's status row, merging the durable outcome with
 * in-flight progress. `last_success_ms`, `dataset_version` and `row_count`
 * describe the dataset actually installed — they keep describing a previous
 * success even while a new run is `"running"` or after one has `"failed"`
 * (SPEC §27: a failed import leaves the previous dataset intact). */
export interface MetadataSourceStatusEntry {
  name: string;
  status: MetadataSourceStatus;
  last_success_ms: number | null;
  dataset_version: string | null;
  row_count: number | null;
  last_error: string | null;
}

export interface MetadataStatusResponse {
  sources: MetadataSourceStatusEntry[];
}

/** Response to `POST /metadata/update`. `already_running` is `true` when the
 * trigger coalesced onto a run already in flight rather than starting a new
 * one — `started_ms` is that run's start either way. */
export interface MetadataUpdateTriggerResponse {
  started: boolean;
  already_running: boolean;
  started_ms: number;
}

const METADATA_STATUS_PATH = "/api/internal/metadata/status";
const METADATA_UPDATE_PATH = "/api/internal/metadata/update";

/** How often the Settings page polls while a source is `"running"`. Short
 * enough that a card visibly updates soon after an import finishes, long
 * enough not to spam the backend during a multi-second download. */
export const METADATA_POLL_INTERVAL_MS = 1500;

export function getMetadataStatus(): Promise<MetadataStatusResponse> {
  return apiFetch<MetadataStatusResponse>(METADATA_STATUS_PATH);
}

/** Starts (or reports the state of) an "Update Aircraft Metadata" run.
 * Resolves as soon as the backend answers 202 — the run itself keeps going
 * in the background, tracked by polling {@link useMetadataStatusQuery}. */
export function triggerMetadataUpdate(): Promise<MetadataUpdateTriggerResponse> {
  return apiFetch<MetadataUpdateTriggerResponse>(METADATA_UPDATE_PATH, {
    method: "POST",
  });
}

/** Query key for the shared metadata status document. */
export const metadataStatusQueryKey = ["metadata", "status"] as const;

/** Loads per-source metadata status, polling every
 * {@link METADATA_POLL_INTERVAL_MS} while any source is `"running"` and
 * stopping the instant every source has settled into a terminal status. */
export function useMetadataStatusQuery(): UseQueryResult<MetadataStatusResponse> {
  return useQuery({
    queryKey: metadataStatusQueryKey,
    queryFn: getMetadataStatus,
    refetchInterval: (query) => {
      const sources = query.state.data?.sources ?? [];
      const anyRunning = sources.some((source) => source.status === "running");
      return anyRunning ? METADATA_POLL_INTERVAL_MS : false;
    },
  });
}

/** True when this source row proves a dataset is actually installed.
 *
 * `row_count` is written only by a successful promotion and cleared only by
 * a metadata reset, so a positive count is the single field that separates
 * "an import ran and installed rows" from "registered but never run", "still
 * downloading its first dataset", and "failed with nothing to show". It
 * deliberately keeps describing the installed dataset while a later run is
 * `"running"` or after one has `"failed"` (SPEC §27: a failed import leaves
 * the previous dataset intact) — neither of those takes the data away, so
 * neither should take the metadata-backed filters away. */
function sourceHasRows(source: MetadataSourceStatusEntry): boolean {
  return source.row_count !== null && source.row_count > 0;
}

/** Whether a status document reports any source with rows installed.
 * `undefined` — status not loaded yet, or the request failed — reads as
 * "no metadata", the safe answer: a filter that would silently match
 * nothing stays visibly unavailable until we know better. */
export function hasImportedMetadata(
  status: MetadataStatusResponse | undefined,
): boolean {
  return status?.sources.some(sourceHasRows) ?? false;
}

/** Does this install have aircraft metadata for the metadata-backed filters
 * (classification, mission, type/operator) to match against?
 *
 * Reads {@link useMetadataStatusQuery} rather than fetching the status
 * document a second time: one query key with one set of options, however
 * many components ask. While the status is loading or errored this answers
 * `false`, so a gated control opens up only on positive evidence and never
 * flashes enabled before turning itself off again. */
export function useMetadataAvailable(): boolean {
  const { data } = useMetadataStatusQuery();
  return hasImportedMetadata(data);
}

/** Triggers an update and refreshes {@link useMetadataStatusQuery} with an
 * immediate refetch, so the "running" state (and the polling it drives)
 * shows up as soon as the backend has scheduled the run rather than waiting
 * for the next scheduled poll. */
export function useTriggerMetadataUpdateMutation(): UseMutationResult<
  MetadataUpdateTriggerResponse,
  Error,
  void
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: triggerMetadataUpdate,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: metadataStatusQueryKey });
    },
  });
}
