/**
 * The Sightings page's summary line (slice 098): what the selected window
 * held, in four live figures — sightings, distinct aircraft, distinct types,
 * and aircraft the receiver had never heard before it.
 *
 * The first three are shortcuts as well as figures: each switches the page to
 * the grouping that lists exactly what it counts, so "97 aircraft" is one
 * click from the ninety-seven. The fourth is left out over the whole history,
 * where every aircraft was first heard somewhere in the window and the figure
 * would only repeat the aircraft count.
 */
import type { SightingsGroup } from "@/features/sightings/lib/urlState";
import type { AnalyticsCountsResponse } from "@/lib/api/analytics";
import { cn } from "@/lib/utils";

export interface WindowSummaryProps {
  counts: AnalyticsCountsResponse | undefined;
  isLoading: boolean;
  /** True when the counts request failed and nothing is cached. */
  isError: boolean;
  group: SightingsGroup;
  onGroupChange: (group: SightingsGroup) => void;
}

const NUMBER = new Intl.NumberFormat();

function plural(count: number, one: string, many: string): string {
  return count === 1 ? one : many;
}

interface FigureProps {
  count: number;
  label: string;
  /** The grouping this figure counts the rows of. */
  target: SightingsGroup;
  group: SightingsGroup;
  onGroupChange: (group: SightingsGroup) => void;
}

function Figure({ count, label, target, group, onGroupChange }: FigureProps) {
  const active = target === group;
  return (
    <button
      type="button"
      aria-pressed={active}
      data-testid="sightings-summary-figure"
      data-group={target}
      onClick={() => onGroupChange(target)}
      className={cn(
        "rounded-md px-1.5 py-0.5 outline-none transition-colors",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
        active ? "bg-secondary" : "hover:bg-secondary/60",
      )}
    >
      <span className="font-semibold text-foreground tabular-nums">
        {NUMBER.format(count)}
      </span>{" "}
      <span className="text-muted-foreground">{label}</span>
    </button>
  );
}

export function WindowSummary({
  counts,
  isLoading,
  isError,
  group,
  onGroupChange,
}: WindowSummaryProps) {
  if (counts === undefined) {
    return (
      <p role="status" className="min-h-7 text-sm text-muted-foreground">
        {isLoading ? "Counting…" : isError ? "Counts unavailable." : ""}
      </p>
    );
  }
  const wholeHistory = counts.window.preset === "t0";
  return (
    <div
      aria-label="In this window"
      role="group"
      className="flex min-h-7 flex-wrap items-center gap-x-1 gap-y-1 text-sm"
    >
      <Figure
        count={counts.sightings}
        label={plural(counts.sightings, "sighting", "sightings")}
        target="sightings"
        group={group}
        onGroupChange={onGroupChange}
      />
      <span aria-hidden="true" className="text-muted-foreground">
        ·
      </span>
      <Figure
        count={counts.unique_aircraft}
        label="aircraft"
        target="aircraft"
        group={group}
        onGroupChange={onGroupChange}
      />
      <span aria-hidden="true" className="text-muted-foreground">
        ·
      </span>
      <Figure
        count={counts.unique_types}
        label={plural(counts.unique_types, "type", "types")}
        target="types"
        group={group}
        onGroupChange={onGroupChange}
      />
      {!wholeHistory && (
        <>
          <span aria-hidden="true" className="text-muted-foreground">
            ·
          </span>
          <span className="px-1.5 py-0.5">
            <span className="font-semibold text-foreground tabular-nums">
              {NUMBER.format(counts.new_aircraft)}
            </span>{" "}
            <span className="text-muted-foreground">never seen before</span>
          </span>
        </>
      )}
    </div>
  );
}
