/**
 * The history pages' refresh cadences, in one place (review R2-03).
 *
 * Three numbers rather than one, because the pages are not equally live. The
 * activity feed is the surface whose whole job is "what happened while you
 * weren't watching", so it polls fastest; the two tables grow a row at a time
 * and a slower cadence is honest enough; a detail page only changes at all
 * while its subject is still happening.
 *
 * Page 1 only, in every case: the caller passes `false` past the first page,
 * since a poll that re-fetches page 7 of a list that grows at the *front*
 * would shuffle rows under the reader's cursor for no gain.
 */

/** `/aircraft` and `/sightings`, page 1. */
export const LIST_REFRESH_MS = 30_000;

/** `/activity`, page 1. */
export const ACTIVITY_REFRESH_MS = 15_000;

/** `/aircraft/:icao` while the airframe is live, `/sightings/:id` while the
 * sighting is open. */
export const DETAIL_REFRESH_MS = 30_000;
