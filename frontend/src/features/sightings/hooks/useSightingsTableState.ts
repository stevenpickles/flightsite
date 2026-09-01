/**
 * The Sightings page's sort/order/page/filter state, backed directly by the
 * URL — mirrors `features/aircraft-page/hooks/useAircraftTableState.ts`.
 */

import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

import {
  type SightingsTableState,
  parseSightingsTableState,
  serializeSightingsTableState,
} from "@/features/sightings/lib/urlState";

export interface UseSightingsTableStateResult {
  state: SightingsTableState;
  /** Merges a partial update into the current state and writes it back to
   * the URL. Changing anything other than `page` resets `page` to 1 unless
   * the caller explicitly sets a new one — a previous page number rarely
   * still makes sense against a differently sorted or filtered result. */
  setState: (patch: Partial<SightingsTableState>) => void;
}

export function useSightingsTableState(): UseSightingsTableStateResult {
  const [searchParams, setSearchParams] = useSearchParams();

  const state = useMemo(
    () => parseSightingsTableState(searchParams),
    [searchParams],
  );

  const setState = useCallback(
    (patch: Partial<SightingsTableState>) => {
      setSearchParams(
        (previous) => {
          const current = parseSightingsTableState(previous);
          const changesFilterOrSort = Object.keys(patch).some(
            (key) => key !== "page",
          );
          const next: SightingsTableState = {
            ...current,
            ...patch,
            page:
              "page" in patch
                ? (patch.page as number)
                : changesFilterOrSort
                  ? 1
                  : current.page,
          };
          return serializeSightingsTableState(next);
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  return { state, setState };
}
