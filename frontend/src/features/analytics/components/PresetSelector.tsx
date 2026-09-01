/**
 * The Analytics page's time-preset selector (SPEC §58: Today / 7 days /
 * 30 days / This year / Since T0), URL-persisted via
 * `useAnalyticsPresetState`. A `role="radiogroup"` of toggle buttons rather
 * than a `<select>` — five short, mutually-exclusive options read faster as
 * always-visible buttons than behind a dropdown, and the roving `aria-checked`
 * state keeps this understandable to assistive tech as one choice, not five
 * independent toggles.
 */
import { useRef } from "react";

import { ANALYTICS_PRESETS, type AnalyticsPreset } from "@/lib/api/analytics";

import { PRESET_LABELS } from "@/features/analytics/lib/urlState";
import { useRovingFocus } from "@/lib/a11y/useRovingFocus";
import { cn } from "@/lib/utils";

export interface PresetSelectorProps {
  preset: AnalyticsPreset;
  onChange: (preset: AnalyticsPreset) => void;
}

export function PresetSelector({ preset, onChange }: PresetSelectorProps) {
  // A radiogroup is one tab stop; the arrows move (and select) within it.
  // `both` because the group wraps, so "down" reads as "next" too.
  const groupRef = useRef<HTMLDivElement>(null);
  const onKeyDown = useRovingFocus(groupRef, {
    itemRole: "radio",
    orientation: "both",
  });

  return (
    <div
      role="radiogroup"
      aria-label="Time range"
      ref={groupRef}
      onKeyDown={onKeyDown}
      className="inline-flex flex-wrap gap-1 rounded-lg border border-border bg-card p-1"
    >
      {ANALYTICS_PRESETS.map((option) => {
        const active = option === preset;
        return (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={active}
            // The preset's identity, not just its prose label: the E2E suite
            // asserts every window in SPEC §82's "Analytics windows" flow
            // against the value that reaches the API and the URL, so it does
            // not have to keep a copy of these five display strings in step.
            data-testid="analytics-preset"
            data-preset={option}
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
            {PRESET_LABELS[option]}
          </button>
        );
      })}
    </div>
  );
}
