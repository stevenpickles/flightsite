/**
 * The list pages' `q` search, as the client stores and sends it (roadmap
 * slice 083, `docs/API.md` §3.5/§3.6). Shared by `/aircraft` and
 * `/sightings`, which each send `q` to their own endpoint only — list-scoped
 * filtering, not a global search (SPEC §37; a cross-entity search is §79's
 * deferred non-goal).
 *
 * The server trims `q`, ignores a blank one and rejects one over its cap with
 * a 422; normalizing the same way here keeps the URL, the input and the
 * request in agreement, and turns a hand-edited over-long link into a search
 * the server accepts rather than an error page.
 */

/** The API's cap on `q` (`MAX_QUERY_LENGTH` in `flightsite.api.search`). */
export const MAX_SEARCH_LENGTH = 32;

/** The shortest search the pages will send. The API accepts one character,
 * but a single letter matches a large share of history — the one query
 * shape measured near the query budget on a three-year database — and is
 * rarely what anyone meant, so the boxes wait for a second character. */
export const MIN_SEARCH_LENGTH = 2;

/** Whether a normalized search is present but too short to send. */
export function isTooShort(q: string | undefined): boolean {
  return q !== undefined && q.length < MIN_SEARCH_LENGTH;
}

/** A search read from a URL: normalized, and dropped when too short to send,
 * so a hand-edited `?q=a` shows the unfiltered list rather than issuing the
 * query the boxes themselves never would. */
export function searchFromUrl(raw: string | null): string | undefined {
  const q = normalizeSearch(raw);
  return isTooShort(q) ? undefined : q;
}

/** A search as the API will read it: trimmed, capped at
 * {@link MAX_SEARCH_LENGTH}, and `undefined` when nothing is left — so an
 * input holding only spaces is "no search", not a search for spaces. */
export function normalizeSearch(
  raw: string | null | undefined,
): string | undefined {
  const trimmed = (raw ?? "").trim().slice(0, MAX_SEARCH_LENGTH).trim();
  return trimmed === "" ? undefined : trimmed;
}
