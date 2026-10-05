/**
 * How the Sightings page groups its window (slice 098): the log itself, one
 * row per distinct aircraft, or one row per distinct type. A
 * `role="radiogroup"` of toggle buttons, the same control the time-preset
 * selector beside it is (`features/analytics/components/PresetSelector.tsx`)
 * — three short, mutually exclusive options read faster as always-visible
 * buttons than behind a dropdown.
 */
import { useRef } from "react";

import {
  SIGHTINGS_GROUPS,
  type SightingsGroup,
} from "@/features/sightings/lib/urlState";
import { useRovingFocus } from "@/lib/a11y/useRovingFocus";
import { cn } from "@/lib/utils";

const GROUP_LABELS: Record<SightingsGroup, string> = {
  sightings: "Sightings",
  aircraft: "Aircraft",
  types: "Types",
};

export interface GroupSelectorProps {
  group: SightingsGroup;
  onChange: (group: SightingsGroup) => void;
}

export function GroupSelector({ group, onChange }: GroupSelectorProps) {
  const groupRef = useRef<HTMLDivElement>(null);
  const onKeyDown = useRovingFocus(groupRef, {
    itemRole: "radio",
    orientation: "both",
  });

  return (
    <div className="flex items-center gap-2">
      <span
        id="sightings-group-label"
        className="text-sm text-muted-foreground"
      >
        Group by
      </span>
      <div
        role="radiogroup"
        aria-labelledby="sightings-group-label"
        ref={groupRef}
        onKeyDown={onKeyDown}
        className="inline-flex flex-wrap gap-1 rounded-lg border border-border bg-card p-1"
      >
        {SIGHTINGS_GROUPS.map((option) => {
          const active = option === group;
          return (
            <button
              key={option}
              type="button"
              role="radio"
              aria-checked={active}
              data-testid="sightings-group"
              data-group={option}
              tabIndex={active ? 0 : -1}
              onClick={() => onChange(option)}
              className={cn(
                "rounded-md px-3 py-1.5 text-sm font-medium outline-none transition-colors",
                "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                active
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-secondary hover:text-foreground",
              )}
            >
              {GROUP_LABELS[option]}
            </button>
          );
        })}
      </div>
    </div>
  );
}
