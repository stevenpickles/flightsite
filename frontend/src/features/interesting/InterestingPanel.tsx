/**
 * The interesting-aircraft panel (SPEC §49, roadmap slice 039).
 *
 * *"Persistent or easily accessible panel listing currently interesting
 * aircraft. Sort by severity, then distance ... Clicking selects the
 * aircraft."* This is the persistent reading of that: the card is always on
 * the Live Map and **expanded by default**, unlike the `NonPositionedPanel`
 * and `ActivityPanel` it otherwise copies. A panel whose job is to draw
 * attention to a critical squawk cannot start folded away; the count badge
 * alone would make the user click to discover something was wrong.
 *
 * Where the rows come from
 * ------------------------
 * `useFilteredLiveAircraft` — the same `FilterResult` the map itself just
 * drew, not a separately-computed approximation and not a second HTTP
 * resource (`lib/ordering.ts` covers why the ordering is local). Reading the
 * *filtered* set is a deliberate choice with a real trade-off:
 *
 * - **For:** every other Live Map panel does it, and a user who narrowed the
 *   picture expects the panels beside it to agree. A panel listing aircraft
 *   the map is not drawing is a panel whose "click to select" lands on an
 *   invisible target.
 * - **Against:** an unrelated filter (say an altitude band) can hide a
 *   critical match. That is why the header keeps showing the *unfiltered*
 *   total and says how many are hidden, rather than quietly under-reporting:
 *   the filter narrows the list, it never silently narrows the count.
 *
 * The "Interesting only" filter (`features/filters`) is the inverse tool —
 * it narrows the *map* to this panel's set — and this slice activates it, in
 * the sense that `interesting` is now a value the backend actually populates
 * (slice 038) rather than a permanently-`null` field the filter matched
 * nothing against.
 */

import { ChevronDown, ChevronUp } from "lucide-react";
import { useState } from "react";

import { useFilteredLiveAircraft } from "@/features/filters/hooks/useFilteredLiveAircraft";
import { InterestingRow } from "@/features/interesting/components/InterestingRow";
import { orderInterestingAircraft } from "@/features/interesting/lib/ordering";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";

export function InterestingPanel() {
  const [isExpanded, setIsExpanded] = useState(true);
  const { aircraft } = useFilteredLiveAircraft();
  const allAircraft = useLiveAircraftStore((state) => state.aircraft);
  const receiver = useLiveAircraftStore((state) => state.receiver);
  const selectedIcao = useLiveAircraftStore((state) => state.selectedIcao);
  const selectAircraft = useLiveAircraftStore((state) => state.selectAircraft);

  const units = receiver?.units ?? "aviation";
  const rows = orderInterestingAircraft(aircraft);

  // The unfiltered count, so a filter that hides a match says so rather than
  // making the panel look empty. Cheap: one pass over the live records, the
  // same pass the filter itself already makes.
  let total = 0;
  for (const icao in allAircraft) {
    if (allAircraft[icao]?.aircraft.interesting) {
      total += 1;
    }
  }
  const hidden = total - rows.length;

  return (
    <div
      data-testid="interesting-panel"
      className="pointer-events-auto overflow-hidden rounded-lg border border-border bg-card/95 shadow-md backdrop-blur-sm"
    >
      <button
        type="button"
        aria-expanded={isExpanded}
        onClick={() => setIsExpanded((expanded) => !expanded)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-xs font-medium"
      >
        <span className="flex items-center gap-1.5">
          Interesting
          <span
            data-testid="interesting-count"
            className="inline-flex min-w-4 items-center justify-center rounded-full bg-secondary px-1 text-[10px] font-semibold text-secondary-foreground"
          >
            {total}
          </span>
        </span>
        {isExpanded ? (
          <ChevronUp className="size-3.5" aria-hidden="true" />
        ) : (
          <ChevronDown className="size-3.5" aria-hidden="true" />
        )}
      </button>

      {isExpanded && (
        <div className="border-t border-border">
          {rows.length === 0 ? (
            <p className="px-3 py-2 text-xs text-muted-foreground">
              {total === 0
                ? "No interesting aircraft right now."
                : "Every interesting aircraft is hidden by the current filters."}
            </p>
          ) : (
            <ul className="max-h-64 overflow-y-auto">
              {rows.map((entry) => (
                <InterestingRow
                  key={entry.aircraft.icao}
                  entry={entry}
                  units={units}
                  selected={entry.aircraft.icao === selectedIcao}
                  onSelect={selectAircraft}
                />
              ))}
            </ul>
          )}
          {hidden > 0 && rows.length > 0 && (
            <p
              data-testid="interesting-hidden-note"
              className="border-t border-border px-3 py-1.5 text-[11px] text-muted-foreground"
            >
              {hidden} hidden by the current filters.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
