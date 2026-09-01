/**
 * Typed client for `POST /api/internal/reset/*` (docs/API.md §5, SPEC §73,
 * roadmap slice 045). Both actions are destructive and require an exact
 * typed-confirmation phrase in the body — see
 * `_require_confirm_phrase` in `backend/src/flightsite/api/internal.py`,
 * which this file's constants mirror character for character.
 */
import {
  useMutation,
  useQueryClient,
  type UseMutationResult,
} from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import { metadataStatusQueryKey } from "@/lib/api/metadata";

/** The exact phrase `POST /reset/metadata-cache` requires. */
export const CLEAR_METADATA_CONFIRM_PHRASE = "clear-metadata";
/** The exact phrase `POST /reset/data` requires. */
export const RESET_DATA_CONFIRM_PHRASE = "reset-flightsite-data";

const CLEAR_METADATA_PATH = "/api/internal/reset/metadata-cache";
const RESET_DATA_PATH = "/api/internal/reset/data";

/** Row counts `POST /reset/metadata-cache` removed — mirrors
 * `ClearMetadataResult.as_dict()` in `flightsite.reset.service`. Aircraft,
 * sighting and analytics history is never part of this response because the
 * action never touches it. */
export interface ClearMetadataCacheResponse {
  cleared: boolean;
  aircraft_metadata_rows: number;
  staging_rows: number;
  resolved_rows: number;
  classification_rows: number;
  operator_rows: number;
  operator_group_rows: number;
  route_cache_rows: number;
  airport_rows: number;
  sources_reset: number;
}

/** `POST /reset/data`'s response. `restart_required` is always `true` —
 * the action is mark-and-restart (`flightsite.reset.marker`): the database
 * is untouched until the next process start. */
export interface ResetFlightSiteDataResponse {
  accepted: boolean;
  requested_ms: number;
  restart_required: boolean;
  message: string;
}

function clearMetadataCache(): Promise<ClearMetadataCacheResponse> {
  return apiFetch<ClearMetadataCacheResponse>(CLEAR_METADATA_PATH, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirm: CLEAR_METADATA_CONFIRM_PHRASE }),
  });
}

function resetFlightSiteData(): Promise<ResetFlightSiteDataResponse> {
  return apiFetch<ResetFlightSiteDataResponse>(RESET_DATA_PATH, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirm: RESET_DATA_CONFIRM_PHRASE }),
  });
}

/** Clears the metadata cache and refreshes the "Aircraft Metadata" section's
 * status query, so its source cards read "never run" immediately rather than
 * a stale success from before the clear. */
export function useClearMetadataCacheMutation(): UseMutationResult<
  ClearMetadataCacheResponse,
  Error,
  void
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: clearMetadataCache,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: metadataStatusQueryKey });
    },
  });
}

/** Requests the full reset. Nothing to invalidate: the response is a
 * promise about the *next* restart, not a change to anything this session
 * has loaded. */
export function useResetFlightSiteDataMutation(): UseMutationResult<
  ResetFlightSiteDataResponse,
  Error,
  void
> {
  return useMutation({ mutationFn: resetFlightSiteData });
}
