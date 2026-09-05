/**
 * A route end FlightSite worked out for itself — SPEC §28 as amended for
 * slice 071.
 *
 * When no source knows a callsign's route, the slice-027 airport context can
 * still say where the aircraft is: an aircraft climbing away from a field it
 * has just left is, in every practical sense, departing from there. §28 lets
 * the panel say so, and requires in the same sentence that "externally
 * reported route information" stay distinguishable from "locally inferred
 * airport context". Three things keep them apart here:
 *
 * 1. **Inference never competes with a report.** A reported ident always
 *    wins; inference fills a hole, it never overwrites an answer.
 * 2. **It looks different.** The ident renders muted rather than in the
 *    emphasis a reported endpoint carries, and wears a literal `inferred`
 *    tag — text, not a colour, per SPEC §80.
 * 3. **It says so on hover and to assistive tech.** The tag's `title` spells
 *    out what was inferred and from what, and ends by saying it is not a
 *    reported route.
 *
 * Nothing here is written back: the payload's `route` block is untouched, and
 * the `Nearest airport` section still shows the same field on its own terms.
 */
import type { ReactNode } from "react";

import type { LiveAircraft, NearestAirportInfo } from "@/lib/api/live";

/** Which end of the route is being rendered. */
export type RouteEnd = "origin" | "destination";

/** The inferred phase that can stand in for each end. `docs/DATA_MODEL.md`
 * §2.3's vocabulary is `arriving` / `departing`: an aircraft departing a
 * field makes that field the origin, one arriving makes it the destination.
 * Any other phase — including `null`, which is what an ambiguous or
 * on-the-ground aircraft gets — infers nothing. */
const PHASE_FOR_END: Record<
  RouteEnd,
  NonNullable<NearestAirportInfo["phase"]>
> = {
  origin: "departing",
  destination: "arriving",
};

/** The sentence the `inferred` tag carries, per end. */
const INFERRED_EXPLANATION: Record<RouteEnd, string> = {
  origin:
    "Inferred from the aircraft's departure at this field; not a reported route.",
  destination:
    "Inferred from the aircraft's approach to this field; not a reported route.",
};

/** The airport that may stand in for one end of the route, or `null` when
 * nothing may.
 *
 * Deliberately conservative, and each guard is a rule rather than a
 * defensive habit: a reported ident wins outright, an aircraft with no
 * nearest-airport context infers nothing, and a phase that does not match
 * the end infers nothing either — an aircraft arriving somewhere says
 * nothing about where it started.
 *
 * Tolerates a payload older than slice 027, where `nearest_airport` is
 * absent rather than `null`. */
export function inferredRouteEnd(
  aircraft: LiveAircraft,
  end: RouteEnd,
): NearestAirportInfo | null {
  // `?? null` rather than a comparison against `undefined`: a payload from a
  // backend older than slice 070 can omit the key entirely, and normalising
  // it here keeps the guard below a single question.
  const reported =
    (end === "origin" ? aircraft.route.origin : aircraft.route.destination) ??
    null;
  if (reported !== null) {
    return null;
  }
  const airport = aircraft.nearest_airport ?? null;
  if (airport === null) {
    return null;
  }
  return airport.phase === PHASE_FOR_END[end] ? airport : null;
}

export interface InferredRouteEndValueProps {
  airport: NearestAirportInfo;
  end: RouteEnd;
}

/** Returns the `value` a `FieldRow` should render for an inferred route end
 * — a function, like `routeEndpointValue`, so both endpoint renderers plug
 * into the same row the same way. */
export function inferredRouteEndValue({
  airport,
  end,
}: InferredRouteEndValueProps): ReactNode {
  // A pre-slice-070 payload can carry an ident with no name beside it.
  const name = airport.name || null;
  return (
    <span className="inline-flex items-baseline gap-1.5 font-normal text-muted-foreground">
      <span>{airport.ident}</span>
      {name !== null && (
        <span title={name} className="max-w-[8rem] truncate text-xs">
          {name}
        </span>
      )}
      <span
        title={INFERRED_EXPLANATION[end]}
        className="shrink-0 rounded border border-border px-1 py-0.5 text-[0.625rem] font-medium uppercase tracking-wide"
      >
        inferred
      </span>
    </span>
  );
}
