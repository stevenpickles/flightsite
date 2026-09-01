/**
 * The non-positioned aircraft list (roadmap slice 017): Mode S contacts
 * FlightSite tracks but cannot draw on the map (SPEC §20 — no position
 * report yet, or ever, for that aircraft). Reads
 * `useFilteredLiveAircraft` — the same filtered result the map itself
 * draws from — so an aircraft filtered out everywhere else (e.g. by
 * altitude, or the live-set search box) is filtered out of this list too.
 *
 * Selecting a row sets `useLiveAircraftStore.selectedIcao` exactly like a
 * map click does, opening `AircraftDetailPanel`; the map obviously cannot
 * fly to an aircraft with no position; the header docstring on
 * `AircraftDetailPanel` covers what a selection without live data — including
 * one FlightSite has never had a fix for — shows instead.
 *
 * The card does **not** position itself. Slice 039 added a second
 * aircraft-list panel to the same bottom-left corner (`InterestingPanel`),
 * so `LiveMapPage` now owns that corner as one flex column and both cards
 * are plain children of it — two absolutely-positioned siblings claiming
 * `bottom-3 left-3` would simply have stacked on top of each other.
 */

import { ChevronDown, ChevronUp } from "lucide-react";
import { useState } from "react";

import { useFilteredLiveAircraft } from "@/features/filters/hooks/useFilteredLiveAircraft";
import { useFilterStore } from "@/features/filters/store/useFilterStore";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { cn } from "@/lib/utils";

function formatAltitude(altitudeFt: number | null): string {
  return altitudeFt === null ? "—" : `${Math.round(altitudeFt)} ft`;
}

export function NonPositionedPanel() {
  const hideNonPositioned = useFilterStore(
    (state) => state.filters.hideNonPositioned,
  );
  const { aircraft } = useFilteredLiveAircraft();
  const selectedIcao = useLiveAircraftStore((state) => state.selectedIcao);
  const selectAircraft = useLiveAircraftStore((state) => state.selectAircraft);
  const [isExpanded, setIsExpanded] = useState(false);

  if (hideNonPositioned) {
    return null;
  }

  const nonPositioned = aircraft.filter((view) => view.position === null);

  return (
    <div
      data-testid="non-positioned-panel"
      className="pointer-events-auto overflow-hidden rounded-lg border border-border bg-card/95 shadow-md backdrop-blur-sm"
    >
      <button
        type="button"
        aria-expanded={isExpanded}
        onClick={() => setIsExpanded((expanded) => !expanded)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-xs font-medium"
      >
        <span className="flex items-center gap-1.5">
          Non-positioned
          <span
            data-testid="non-positioned-count"
            className="inline-flex min-w-4 items-center justify-center rounded-full bg-secondary px-1 text-[10px] font-semibold text-secondary-foreground"
          >
            {nonPositioned.length}
          </span>
        </span>
        {isExpanded ? (
          <ChevronUp className="size-3.5" aria-hidden="true" />
        ) : (
          <ChevronDown className="size-3.5" aria-hidden="true" />
        )}
      </button>

      {isExpanded && (
        <ul className="max-h-56 overflow-y-auto border-t border-border">
          {nonPositioned.length === 0 ? (
            <li className="px-3 py-2 text-xs text-muted-foreground">
              No non-positioned aircraft in the live set.
            </li>
          ) : (
            nonPositioned.map((view) => {
              const selected = view.icao === selectedIcao;
              return (
                <li key={view.icao}>
                  <button
                    type="button"
                    onClick={() => selectAircraft(view.icao)}
                    aria-current={selected}
                    className={cn(
                      "flex w-full flex-col gap-0.5 border-b border-border px-3 py-1.5 text-left text-xs last:border-b-0",
                      "outline-none transition-colors hover:bg-secondary focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring",
                      selected && "bg-accent/20",
                    )}
                  >
                    <span className="font-medium">
                      {view.callsign ?? view.icao.toUpperCase()}
                    </span>
                    <span className="text-muted-foreground">
                      ICAO {view.icao.toUpperCase()} ·{" "}
                      {formatAltitude(view.altitude_ft)} · Squawk{" "}
                      {view.squawk ?? "—"} · RSSI{" "}
                      {view.rssi_db === null
                        ? "—"
                        : `${view.rssi_db.toFixed(1)} dB`}
                    </span>
                  </button>
                </li>
              );
            })
          )}
        </ul>
      )}
    </div>
  );
}
