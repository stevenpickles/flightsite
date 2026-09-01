/**
 * The Aircraft page's sort/order/page state, backed directly by the URL
 * (roadmap slice 029: "URL-persisted sort/page"). Unlike the live filters
 * (`useFilterUrlSync`), there is no separate store to keep in sync — the URL
 * *is* the state, read fresh on every render and written with `replace` so
 * paging/sorting never grows the browser history stack.
 */

import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

import {
  type AircraftTableState,
  parseAircraftTableState,
  serializeAircraftTableState,
} from "@/features/aircraft-page/lib/urlState";

export interface UseAircraftTableStateResult {
  state: AircraftTableState;
  /** Merges a partial update into the current state and writes it back to
   * the URL. Changing `sort` or `order` resets `page` to 1 unless the
   * caller explicitly sets a new one — the previous page number rarely
   * still makes sense against a differently-ordered result. */
  setState: (patch: Partial<AircraftTableState>) => void;
}

export function useAircraftTableState(): UseAircraftTableStateResult {
  const [searchParams, setSearchParams] = useSearchParams();

  const state = useMemo(
    () => parseAircraftTableState(searchParams),
    [searchParams],
  );

  const setState = useCallback(
    (patch: Partial<AircraftTableState>) => {
      setSearchParams(
        (previous) => {
          const current = parseAircraftTableState(previous);
          const resettingPage =
            !("page" in patch) &&
            (("sort" in patch && patch.sort !== current.sort) ||
              ("order" in patch && patch.order !== current.order));
          const next: AircraftTableState = {
            ...current,
            ...patch,
            page: resettingPage ? 1 : (patch.page ?? current.page),
          };
          return serializeAircraftTableState(next);
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  return { state, setState };
}
