/**
 * The Activity page's page/filter state, backed directly by the URL —
 * mirrors `features/sightings/hooks/useSightingsTableState.ts`.
 */

import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

import {
  type ActivityPageState,
  parseActivityPageState,
  serializeActivityPageState,
} from "@/features/activity/lib/urlState";

export interface UseActivityPageStateResult {
  state: ActivityPageState;
  /** Merges a partial update into the current state and writes it back to
   * the URL. Changing anything other than `page` resets `page` to 1 unless
   * the caller explicitly sets a new one — page 4 of an unfiltered feed
   * rarely means anything once a type filter is applied. */
  setState: (patch: Partial<ActivityPageState>) => void;
}

export function useActivityPageState(): UseActivityPageStateResult {
  const [searchParams, setSearchParams] = useSearchParams();

  const state = useMemo(
    () => parseActivityPageState(searchParams),
    [searchParams],
  );

  const setState = useCallback(
    (patch: Partial<ActivityPageState>) => {
      setSearchParams(
        (previous) => {
          const current = parseActivityPageState(previous);
          const changesFilter = Object.keys(patch).some(
            (key) => key !== "page",
          );
          const next: ActivityPageState = {
            ...current,
            ...patch,
            page:
              "page" in patch
                ? (patch.page as number)
                : changesFilter
                  ? 1
                  : current.page,
          };
          return serializeActivityPageState(next);
        },
        // `replace` so paging and filtering do not fill the browser's back
        // stack — the same call every other URL-state hook here makes.
        { replace: true },
      );
    },
    [setSearchParams],
  );

  return { state, setState };
}
