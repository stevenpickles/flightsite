/**
 * Sightings-specific formatting: duration (which, unlike the aircraft
 * detail panel's track-duration display, routinely spans hours), and the
 * plain-language closure-reason vocabulary (§2.8) for the log's tooltip.
 */

import type { ClosureReason } from "@/lib/api/sightings";

/** `"3m 12s"`, `"1h 04m"`, `"2d 3h"` — a sighting's duration, in whichever
 * unit keeps the string short. `null` (an open sighting has none yet) is the
 * caller's job to render as "Ongoing" — this only formats a real duration. */
export function formatSightingDuration(durationS: number): string {
  const totalSeconds = Math.max(0, Math.floor(durationS));
  const days = Math.floor(totalSeconds / 86_400);
  const hours = Math.floor((totalSeconds % 86_400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (days > 0) {
    return `${days}d ${hours}h`;
  }
  if (hours > 0) {
    return `${hours}h ${String(minutes).padStart(2, "0")}m`;
  }
  if (minutes > 0) {
    return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
  }
  return `${seconds}s`;
}

export interface ClosureReasonInfo {
  label: string;
  description: string;
}

/** Plain-language explanation of §2.8's `closure_reason` vocabulary, for the
 * log's tooltip and the detail view's summary header. */
export const CLOSURE_REASON_INFO: Record<ClosureReason, ClosureReasonInfo> = {
  gap_timeout: {
    label: "Timed out",
    description:
      "The aircraft was not heard again for the configured absence gap.",
  },
  shutdown_recovery: {
    label: "Recovered at restart",
    description:
      "FlightSite was not running to observe the end of this sighting; it was closed when the application restarted.",
  },
  data_reset: {
    label: "Data reset",
    description: "This sighting was closed by a user-initiated data reset.",
  },
};

export function describeClosureReason(
  reason: ClosureReason | null,
): ClosureReasonInfo | null {
  return reason === null ? null : CLOSURE_REASON_INFO[reason];
}
