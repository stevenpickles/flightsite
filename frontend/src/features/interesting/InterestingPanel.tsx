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
import {
  groupInterestingBySeverity,
  meritsAttention,
  orderInterestingAircraft,
} from "@/features/interesting/lib/ordering";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { cn } from "@/lib/utils";

/** The browser's own wall-clock reading of a `Date.now()` value — what
 * `lastUpdate` is measured on, so it is the clock to render it against
 * (the receiver's, which the rest of the app formats history in, is a
 * different one and may be skewed from it). */
function clockTime(at: number): string {
  return new Date(at).toLocaleTimeString();
}

/**
 * What an empty panel says, given whether anything is still feeding it.
 *
 * "No interesting aircraft right now" is an assertion about the sky, and
 * issue R1-03 is that the panel went on making it through every outage —
 * loudest at exactly the moment it was least entitled to. It is said only
 * when the picture is live. Otherwise the sentence is about the feed, and
 * about how old the answer is.
 */
function emptyStateText(stale: boolean, lastUpdate: number | null): string {
  if (!stale) {
    return "No interesting aircraft right now.";
  }
  if (lastUpdate === null) {
    return "Waiting for the live feed — no picture yet.";
  }
  return `Feed lost. None as of ${clockTime(lastUpdate)}.`;
}

export function InterestingPanel() {
  const [isExpanded, setIsExpanded] = useState(true);
  // Folded by default, and the one thing on this panel that starts folded:
  // an `info` match is by construction the least urgent thing the alert
  // engine can say, and on a new install there are dozens of them.
  const [showInfo, setShowInfo] = useState(false);
  const { aircraft } = useFilteredLiveAircraft();
  const allAircraft = useLiveAircraftStore((state) => state.aircraft);
  const stale = useLiveAircraftStore((state) => state.stale);
  const lastUpdate = useLiveAircraftStore((state) => state.lastUpdate);
  const receiver = useLiveAircraftStore((state) => state.receiver);
  const selectedIcao = useLiveAircraftStore((state) => state.selectedIcao);
  const selectAircraft = useLiveAircraftStore((state) => state.selectAircraft);

  const units = receiver?.units ?? "aviation";
  const rows = orderInterestingAircraft(aircraft);
  const { prominent, info } = groupInterestingBySeverity(rows);

  // The unfiltered counts, so a filter that hides a match says so rather than
  // making the panel look empty. Cheap: one pass over the live records, the
  // same pass the filter itself already makes.
  //
  // Counted in two, for the same reason the list is grouped in two: the
  // review's install had 76 of 77 aircraft matching `first_ever`, and a
  // badge reading "76" beside a live set of 77 is not a count of anything a
  // watcher can act on (issue R1-10). The badge leads with what is above
  // `info`; the info matches are a number on the toggle below, never hidden.
  let totalProminent = 0;
  let totalInfo = 0;
  for (const icao in allAircraft) {
    const match = allAircraft[icao]?.aircraft.interesting;
    if (!match) {
      continue;
    }
    if (meritsAttention(match.severity)) {
      totalProminent += 1;
    } else {
      totalInfo += 1;
    }
  }
  const total = totalProminent + totalInfo;
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
            {totalProminent}
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
            <p
              data-testid="interesting-empty"
              className="px-3 py-2 text-xs text-muted-foreground"
            >
              {total > 0
                ? "Every interesting aircraft is hidden by the current filters."
                : emptyStateText(stale, lastUpdate)}
            </p>
          ) : (
            <>
              {prominent.length === 0 && (
                // The whole of a stock install's first weeks: plenty
                // matching, nothing above `info`. Saying so beats an empty
                // scroll box above a "+76 info" button.
                <p
                  data-testid="interesting-none-prominent"
                  className="px-3 py-2 text-xs text-muted-foreground"
                >
                  Nothing above info level right now.
                </p>
              )}
              {(prominent.length > 0 || showInfo) && (
                <ul
                  // Taller while the info group is folded away, since that
                  // is when the space is going to the rows worth reading.
                  className={cn(
                    "overflow-y-auto",
                    showInfo ? "max-h-64" : "max-h-80",
                  )}
                >
                  {(showInfo ? [...prominent, ...info] : prominent).map(
                    (entry) => (
                      <InterestingRow
                        key={entry.aircraft.icao}
                        entry={entry}
                        units={units}
                        selected={entry.aircraft.icao === selectedIcao}
                        onSelect={selectAircraft}
                      />
                    ),
                  )}
                </ul>
              )}
              {info.length > 0 && (
                <button
                  type="button"
                  data-testid="interesting-info-toggle"
                  aria-expanded={showInfo}
                  onClick={() => setShowInfo((shown) => !shown)}
                  className="w-full border-t border-border px-3 py-1.5 text-left text-[11px] text-muted-foreground outline-none hover:bg-secondary focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring"
                >
                  {showInfo
                    ? `Hide ${info.length} info-level`
                    : `+${info.length} info-level`}
                </button>
              )}
            </>
          )}
          {stale && lastUpdate !== null && rows.length > 0 && (
            // A list nobody is updating is still worth showing — it is the
            // last true thing known — but only dated (issue R1-03).
            <p
              data-testid="interesting-stale-note"
              className="border-t border-border px-3 py-1.5 text-[11px] text-muted-foreground"
            >
              Feed lost — as of {clockTime(lastUpdate)}.
            </p>
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
