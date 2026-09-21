/**
 * The selected aircraft's ICAO <-> query string (`?selected=<icao>`, R1-09).
 *
 * A sibling to `urlSync.ts`, kept separate from it rather than folded into
 * `LiveFilters`'s own key set: selection is not a filter (it never narrows
 * what the map draws), and `serializeFiltersToSearchParams` /
 * `parseFiltersFromSearchParams` round-trip a whole `LiveFilters` object,
 * where selection is a single optional string most of the time absent.
 *
 * Pure `URLSearchParams` in and out, exactly like `urlSync.ts` — the router
 * touching half lives in `hooks/useSelectionUrlSync.ts`.
 */

/** The one query-string key this module owns. */
export const SELECTED_ICAO_PARAM = "selected";

/** Reads the selected ICAO out of a query string, or `null` if absent or
 * blank. Lower-cased to match `useLiveAircraftStore`'s keys (lower-case ICAO
 * hex) regardless of how a hand-typed or shared URL capitalized it. */
export function parseSelectedIcaoFromSearchParams(
  params: URLSearchParams,
): string | null {
  const raw = params.get(SELECTED_ICAO_PARAM);
  if (raw === null) {
    return null;
  }
  const trimmed = raw.trim().toLowerCase();
  return trimmed.length > 0 ? trimmed : null;
}

/** Returns a copy of `params` with the selection key set to `icao`, or
 * removed entirely when `icao` is `null` — never a stray `selected=`. */
export function withSelectedIcaoInSearchParams(
  params: URLSearchParams,
  icao: string | null,
): URLSearchParams {
  const next = new URLSearchParams(params);
  if (icao === null) {
    next.delete(SELECTED_ICAO_PARAM);
  } else {
    next.set(SELECTED_ICAO_PARAM, icao);
  }
  return next;
}
