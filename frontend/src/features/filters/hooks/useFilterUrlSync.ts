/**
 * Keeps `useFilterStore` and the URL's query string in sync (roadmap slice
 * 017's "filter state in URL/query where practical"). Mounted once, at
 * `LiveMapPage`.
 *
 * One-way on each edge, not a loop: the URL is read exactly once, on
 * mount, to seed the store (covers a shared/bookmarked filtered link); from
 * then on the store is the source of truth and every change to it pushes a
 * `replace` history entry (never `push` — a filter tweak is not a page a
 * user expects Back to step through). `FILTER_URL_KEYS` scopes the write
 * to only the params this feature owns, so any unrelated query param
 * (there are none today, but the seam costs nothing) survives untouched.
 */

import { useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";

import { useFilterStore } from "@/features/filters/store/useFilterStore";
import {
  FILTER_URL_KEYS,
  parseFiltersFromSearchParams,
  serializeFiltersToSearchParams,
} from "@/features/filters/lib/urlSync";

export function useFilterUrlSync(): void {
  const [searchParams, setSearchParams] = useSearchParams();
  const filters = useFilterStore((state) => state.filters);
  const replaceFilters = useFilterStore((state) => state.replaceFilters);
  // The mount-time seed (URL -> store, below) owns the very first paint;
  // this flag makes the store -> URL effect skip the pass it would
  // otherwise run for that seed's own re-render, so a URL that already
  // named a filter is never briefly overwritten with the defaults.
  const skipNextWrite = useRef(true);

  useEffect(() => {
    replaceFilters(parseFiltersFromSearchParams(searchParams));
    // Deliberately mount-only — see the module doc comment.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (skipNextWrite.current) {
      skipNextWrite.current = false;
      return;
    }
    setSearchParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        for (const key of FILTER_URL_KEYS) {
          next.delete(key);
        }
        for (const [key, value] of serializeFiltersToSearchParams(filters)) {
          next.set(key, value);
        }
        return next;
      },
      { replace: true },
    );
  }, [filters, setSearchParams]);
}
