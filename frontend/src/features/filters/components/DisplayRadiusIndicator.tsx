/**
 * A subtle hint that the display-radius cap (SPEC §66, roadmap slice 017)
 * is hiding traffic — easy to miss otherwise, since a capped aircraft
 * simply never appears rather than being drawn and marked. Silent when
 * nothing is capped, which is the common case (`displayRadiusNm` defaults
 * to 250 nm, wider than most receivers' actual range).
 */

import { useFilteredLiveAircraft } from "@/features/filters/hooks/useFilteredLiveAircraft";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { formatRingLabel } from "@/features/map/geo/rings";
import type { MapCardPlacement } from "@/features/map/phone/placement";
import { cn } from "@/lib/utils";

/**
 * `placement="docked"` (roadmap slice 084) drops the bottom-right anchor so
 * the phone layout can stack the hint in its dock above the bottom toolbar.
 */
export function DisplayRadiusIndicator({
  placement = "floating",
}: {
  placement?: MapCardPlacement;
}) {
  const { distanceCappedCount, effectiveDistanceCapNm } =
    useFilteredLiveAircraft();
  const units = useLiveAircraftStore((state) => state.receiver?.units);

  if (distanceCappedCount === 0) {
    return null;
  }

  return (
    <div
      role="status"
      data-testid="display-radius-indicator"
      className={cn(
        placement === "floating"
          ? "absolute bottom-3 right-3 z-10 max-w-xs"
          : "w-full",
        "pointer-events-none rounded-md border border-border bg-card/90 px-3 py-1.5 text-xs text-muted-foreground shadow-sm backdrop-blur-sm",
      )}
    >
      {distanceCappedCount} aircraft beyond{" "}
      {formatRingLabel(
        effectiveDistanceCapNm,
        units === "metric" ? "km" : "nm",
      )}{" "}
      hidden — still tracked and recorded.
    </div>
  );
}
