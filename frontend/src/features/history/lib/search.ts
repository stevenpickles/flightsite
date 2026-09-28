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

/** A search as the API will read it: trimmed, capped at
 * {@link MAX_SEARCH_LENGTH}, and `undefined` when nothing is left — so an
 * input holding only spaces is "no search", not a search for spaces. */
export function normalizeSearch(
  raw: string | null | undefined,
): string | undefined {
  const trimmed = (raw ?? "").trim().slice(0, MAX_SEARCH_LENGTH).trim();
  return trimmed === "" ? undefined : trimmed;
}
