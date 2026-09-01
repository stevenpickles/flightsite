/**
 * Header position-source badge (scope item 1). Text-driven, not
 * color-only: `position_source` is safety-relevant display state (§3.3,
 * §2.6) — whether a position is a real ADS-B fix, a multilateration
 * estimate, or absent entirely — and SPEC §80 requires that distinction be
 * communicated by text/icon as well as color, so the label word is always
 * the primary signal; the border tint is a secondary cue only.
 */

import type { PositionSource } from "@/lib/api/live";
import { cn } from "@/lib/utils";

const LABELS: Record<PositionSource, string> = {
  adsb: "ADS-B",
  mlat: "MLAT",
  none: "No position",
  other: "Other",
};

const TITLES: Record<PositionSource, string> = {
  adsb: "Position decoded directly from an ADS-B extended squitter.",
  mlat: "Position estimated by multilateration across multiple receivers.",
  none: "No position received — tracked from Mode S only.",
  other: "Position from a source FlightSite doesn't further categorize.",
};

const TONE_CLASSES: Record<PositionSource, string> = {
  adsb: "border-accent/60 text-accent",
  mlat: "border-warning/60 text-warning",
  none: "border-border text-muted-foreground",
  other: "border-border text-muted-foreground",
};

export interface PositionSourceBadgeProps {
  source: PositionSource;
}

export function PositionSourceBadge({ source }: PositionSourceBadgeProps) {
  return (
    <span
      title={TITLES[source]}
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold",
        TONE_CLASSES[source],
      )}
    >
      {LABELS[source]}
    </span>
  );
}
