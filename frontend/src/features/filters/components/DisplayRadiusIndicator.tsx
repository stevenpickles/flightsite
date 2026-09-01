/**
 * A subtle hint that the display-radius cap (SPEC §66, roadmap slice 017)
 * is hiding traffic — easy to miss otherwise, since a capped aircraft
 * simply never appears rather than being drawn and marked. Silent when
 * nothing is capped, which is the common case (`displayRadiusNm` defaults
 * to 250 nm, wider than most receivers' actual range).
 */

import { useFilteredLiveAircraft } from "@/features/filters/hooks/useFilteredLiveAircraft";

export function DisplayRadiusIndicator() {
  const { distanceCappedCount, effectiveDistanceCapNm } =
    useFilteredLiveAircraft();

  if (distanceCappedCount === 0) {
    return null;
  }

  return (
    <div
      role="status"
      data-testid="display-radius-indicator"
      className="pointer-events-none absolute bottom-3 right-3 z-10 max-w-xs rounded-md border border-border bg-card/90 px-3 py-1.5 text-xs text-muted-foreground shadow-sm backdrop-blur-sm"
    >
      {distanceCappedCount} aircraft beyond {effectiveDistanceCapNm} nm hidden —
      still tracked and recorded.
    </div>
  );
}
