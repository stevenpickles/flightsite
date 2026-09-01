/**
 * Ordering for the interesting-aircraft panel (SPEC §49, roadmap slice 039).
 *
 * SPEC §49 asks for *"sort by severity, then distance or other useful
 * secondary ordering"*, and `docs/API.md` §3.4 says the same thing about
 * `GET /api/v1/aircraft/interesting`. This module is the client-side half of
 * that one ordering, and it is deliberately **the same comparison the backend
 * makes** in `LiveApiContext.interesting_aircraft` — severity descending,
 * then distance ascending with the unknown-distance aircraft last, then ICAO
 * as the deterministic tie-break.
 *
 * Why the panel sorts locally rather than polling `/aircraft/interesting`
 * ------------------------------------------------------------------------
 * The panel is fed from `useLiveAircraftStore`, the same live picture the map
 * draws, rather than from a second HTTP resource. Two reasons, and the first
 * is the one that matters:
 *
 * 1. **The panel and the map must never disagree.** A polled list would lag
 *    the socket by up to its poll interval, so an aircraft could sit in the
 *    panel after its alert cleared, or be emphasized on the map while absent
 *    from the panel beside it. Deriving both from one store makes that class
 *    of skew unrepresentable rather than merely unlikely.
 * 2. It costs no request. `interesting` already rides every §3.3 aircraft
 *    object in every snapshot and delta (slice 038), so the data is in the
 *    store before a fetch could have been issued.
 *
 * `GET /api/v1/aircraft/interesting` keeps its own job: it is the *external*
 * read-only answer for LAN tools that are not holding a socket open (SPEC
 * §74). Both orderings being one comparison is what keeps those two answers
 * the same answer, so the ordering test here pins the tie-breaks explicitly.
 */

import type { InterestingMatch, LiveAircraft } from "@/lib/api/live";
import type { AlertSeverity } from "@/lib/api/sightings";

/**
 * `docs/API.md` §2.8's severity ladder as sortable ranks, mirroring
 * `flightsite.alerts.vocabulary.AlertSeverity.rank`.
 *
 * The backend enum is a `StrEnum`, so *it* cannot be compared with `<`
 * either — `"critical" < "info"` alphabetically — and it carries this same
 * explicit rank table for the same reason. Keeping the two in step is why
 * both sides spell the ladder out rather than deriving it from the string.
 */
export const SEVERITY_RANK: Record<AlertSeverity, number> = {
  info: 0,
  interesting: 1,
  high: 2,
  critical: 3,
};

/**
 * The rank for a severity the wire actually carried.
 *
 * Falls back to the bottom of the ladder rather than to `NaN` for a value
 * this build has never heard of: a backend that has learned a fifth severity
 * (§6) should push an unknown aircraft to the end of the panel, not poison
 * the comparison and scramble the whole list.
 */
export function severityRank(severity: AlertSeverity): number {
  return SEVERITY_RANK[severity] ?? 0;
}

/** One row of the panel: a live aircraft and the match that put it there.
 * Pairing them keeps `interesting` non-null in the row's own type, so no
 * consumer re-checks what the filter already established. */
export interface InterestingAircraft {
  aircraft: LiveAircraft;
  interesting: InterestingMatch;
}

/**
 * Severity descending, then distance ascending, then ICAO.
 *
 * An aircraft with no `distance_nm` sorts **last within its severity band**
 * rather than first — the backend's ordering makes the same call, and for the
 * same reason: no distance means no position, and a panel that ranked the
 * aircraft it cannot place above the one overhead would be answering the
 * wrong question. ICAO last makes the order total, so a re-render with two
 * equal-severity, equal-distance aircraft never reshuffles them.
 */
export function compareInterestingAircraft(
  a: InterestingAircraft,
  b: InterestingAircraft,
): number {
  const bySeverity =
    severityRank(b.interesting.severity) - severityRank(a.interesting.severity);
  if (bySeverity !== 0) {
    return bySeverity;
  }
  const byDistance =
    (a.aircraft.distance_nm ?? Number.POSITIVE_INFINITY) -
    (b.aircraft.distance_nm ?? Number.POSITIVE_INFINITY);
  if (byDistance !== 0) {
    return byDistance;
  }
  return a.aircraft.icao.localeCompare(b.aircraft.icao);
}

/**
 * The currently-interesting subset of `views`, in panel order.
 *
 * "Currently" is the whole contract: `interesting` is what is matching *right
 * now* (slice 038's engine clears the block when an aircraft leaves a rule's
 * distance window or its emergency squawk clears), so an aircraft drops out
 * of this list the moment it stops matching. The record of what happened
 * lives in the activity feed and the sighting's own history, not here.
 */
export function orderInterestingAircraft(
  views: readonly LiveAircraft[],
): InterestingAircraft[] {
  const rows: InterestingAircraft[] = [];
  for (const aircraft of views) {
    if (aircraft.interesting !== null) {
      rows.push({ aircraft, interesting: aircraft.interesting });
    }
  }
  return rows.sort(compareInterestingAircraft);
}
