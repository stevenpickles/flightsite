/**
 * One row of the interesting-aircraft panel (SPEC §49).
 *
 * §49 names the row's contents exactly — *"callsign/tail; aircraft type;
 * operator; match reason; distance; altitude"* — and clicking selects the
 * aircraft. All six are here, each degrading to nothing rather than to a
 * placeholder: a compact list is the wrong place to spend a line saying
 * "Unknown" (`docs/API.md` §2.7 makes absence honest, and the detail panel
 * one click away is where the full unknown-aware picture lives).
 *
 * Severity is carried by {@link AlertSeverityBadge} — the same badge the
 * Sightings log already uses for `max_alert_severity`, so one severity
 * vocabulary renders identically everywhere it appears. It is text-first
 * ("Critical", not a red dot), which is what SPEC §80 requires and what the
 * slice's "distinguishable without color alone" criterion is tested against.
 */

import { AlertSeverityBadge } from "@/features/sightings/components/AlertSeverityBadge";
import {
  formatAltitude,
  formatDistance,
} from "@/features/aircraft-detail/lib/format";
import type { InterestingAircraft } from "@/features/interesting/lib/ordering";
import type { UnitSystem } from "@/lib/api/config";
import { cn } from "@/lib/utils";

export interface InterestingRowProps {
  entry: InterestingAircraft;
  units: UnitSystem;
  selected: boolean;
  onSelect: (icao: string) => void;
}

/** Joins the present parts of a line, or `null` when it would be empty —
 * so a row never renders a stray separator for a field the metadata has
 * not resolved. */
function join(parts: readonly (string | null)[]): string | null {
  const present = parts.filter((part): part is string => part !== null);
  return present.length === 0 ? null : present.join(" · ");
}

export function InterestingRow({
  entry,
  units,
  selected,
  onSelect,
}: InterestingRowProps) {
  const { aircraft, interesting } = entry;

  // Callsign, falling back to the tail number, falling back to the ICAO hex
  // the decoder always supplies — the same identity chain the map label uses
  // (`features/map/labels/labelContent.ts`), so an aircraft reads the same
  // in the panel as it does on the map beside it.
  const identity =
    aircraft.callsign ?? aircraft.registration ?? aircraft.icao.toUpperCase();

  const airframe = join([aircraft.aircraft_type, aircraft.operator]);

  // Every reason standing against this aircraft, most severe first (the
  // engine orders them that way). Usually one; two when a second rule caught
  // the same aircraft, which is exactly the case a single-reason row would
  // hide.
  const reasons = interesting.reasons.join(" · ");

  const position = join([
    formatDistance(aircraft.distance_nm, units),
    formatAltitude(aircraft.altitude_ft, units),
  ]);

  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect(aircraft.icao)}
        aria-current={selected}
        data-testid="interesting-row"
        data-icao={aircraft.icao}
        data-severity={interesting.severity}
        className={cn(
          "flex w-full flex-col gap-0.5 border-b border-border px-3 py-2 text-left text-xs last:border-b-0",
          "outline-none transition-colors hover:bg-secondary focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring",
          selected && "bg-accent/20",
        )}
      >
        <span className="flex items-center gap-1.5">
          <AlertSeverityBadge severity={interesting.severity} />
          <span className="truncate font-medium">{identity}</span>
        </span>
        {airframe !== null && (
          <span className="truncate text-muted-foreground">{airframe}</span>
        )}
        {reasons.length > 0 && <span className="truncate">{reasons}</span>}
        {position !== null && (
          <span className="text-muted-foreground">{position}</span>
        )}
      </button>
    </li>
  );
}
