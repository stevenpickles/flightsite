/**
 * The Activity page's type filter: one toggle chip per event kind, reusing
 * the `QuickFilterChips` visual idiom (pill, `aria-pressed`, accent fill when
 * on) because they are the same interaction — a shortcut into state that
 * lives somewhere else, never a second source of truth for it.
 *
 * Multi-select, and additive: with nothing selected the feed is unfiltered,
 * which is both the default and the honest reading of "no filter applied".
 * The selected set goes into the URL as repeated `type=` parameters and
 * straight through to the endpoint, so the chips and the query string and the
 * request are three views of one list.
 */

import { describeActivityType } from "@/features/activity/lib/typeLabels";
import { FILTERABLE_TYPES } from "@/features/activity/lib/urlState";
import type { ActivityEventType } from "@/lib/api/activity";
import { cn } from "@/lib/utils";

export interface ActivityTypeFilterProps {
  selected: readonly ActivityEventType[];
  onChange: (types: readonly ActivityEventType[]) => void;
}

export function ActivityTypeFilter({
  selected,
  onChange,
}: ActivityTypeFilterProps) {
  function toggle(type: ActivityEventType) {
    onChange(
      selected.includes(type)
        ? selected.filter((entry) => entry !== type)
        : [...selected, type],
    );
  }

  return (
    <div
      role="group"
      aria-label="Filter by event type"
      className="mb-4 flex flex-wrap items-center gap-1.5"
    >
      {FILTERABLE_TYPES.map((type) => {
        const active = selected.includes(type);
        return (
          <button
            key={type}
            type="button"
            aria-pressed={active}
            onClick={() => toggle(type)}
            className={cn(
              "rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
              "outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
              active
                ? "border-accent bg-accent text-accent-foreground"
                : "border-border bg-card text-foreground hover:bg-secondary",
            )}
          >
            {describeActivityType(type)}
          </button>
        );
      })}
      {selected.length > 0 && (
        <button
          type="button"
          onClick={() => onChange([])}
          className="ml-1 text-xs text-accent hover:underline"
        >
          Clear
        </button>
      )}
    </div>
  );
}
