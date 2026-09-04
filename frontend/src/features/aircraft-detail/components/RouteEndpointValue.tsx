/**
 * One end of a route — the ICAO/IATA ident the provider filed, plus the
 * airport's name when this install can resolve it locally (slice 070).
 *
 * Three states, and each is deliberate:
 *
 * 1. **Ident with a name** — the ident keeps the emphasis a `FieldRow` value
 *    already carries, and the name follows it in muted text. The name is the
 *    part that can be arbitrarily long ("Seattle-Tacoma International"), so
 *    it is the part that truncates, with the full text on `title` and in the
 *    DOM: CSS truncation is visual only, so a screen reader still reads the
 *    whole name rather than the clipped one.
 * 2. **Ident alone** — rendered as the bare string, byte-for-byte the DOM
 *    this row had before names existed. A backend that has not learned the
 *    airport (or is older than this slice) changes nothing on screen.
 * 3. **No ident** — `null`, so {@link FieldRow} renders `Unknown` exactly as
 *    it does for every other absent value (`docs/API.md` §2.7). A name
 *    without an ident is not a case the contract can produce, and inventing
 *    a display for it would be inventing data.
 */
import type { ReactNode } from "react";

export interface RouteEndpointValueProps {
  ident: string | null;
  /** `undefined` when the payload predates slice 070; treated as `null`. */
  name?: string | null;
}

/** Returns the `value` a `FieldRow` should render for one route endpoint —
 * a function rather than a component so `null` flows into `FieldRow`'s
 * existing `Unknown` path instead of rendering an empty element. */
export function routeEndpointValue({
  ident,
  name,
}: RouteEndpointValueProps): ReactNode {
  if (ident === null) {
    return null;
  }
  const airportName = name ?? null;
  if (airportName === null) {
    return ident;
  }
  return (
    <span className="inline-flex items-baseline gap-1.5">
      <span>{ident}</span>
      <span
        title={airportName}
        className="max-w-[10rem] truncate text-xs font-normal text-muted-foreground"
      >
        {airportName}
      </span>
    </span>
  );
}
