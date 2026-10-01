/**
 * Decoder emergency badge (roadmap slice 086).
 *
 * The ADS-B emergency/priority status an aircraft broadcasts is a second way
 * of declaring an emergency, independent of the squawk — an aircraft can
 * declare minimum fuel or a lifeguard flight on an ordinary code. It gets the
 * same treatment `EmergencySquawkBadge` gives a 7700: prominent, and
 * text-first per §80 (never colour alone) — the kind in plain words is the
 * label, and "ADS-B status" says where it came from, since there is no code to
 * show.
 *
 * The panel renders it only when it adds something to the squawk badge
 * (`decoderEmergencyAddsToSquawk` in `lib/emergency.ts`): a transponder set to
 * 7600 also broadcasts `nordo`, and one emergency should read as one badge.
 */

import { emergencyKindLabel } from "@/lib/emergency";
import type { DecoderEmergency } from "@/lib/api/live";

export interface DecoderEmergencyBadgeProps {
  kind: DecoderEmergency;
}

export function DecoderEmergencyBadge({ kind }: DecoderEmergencyBadgeProps) {
  // `?? kind`: a backend that learned a new kind (§6) still reads as itself.
  const label = emergencyKindLabel(kind) ?? kind;
  return (
    <span
      role="status"
      className="inline-flex items-center gap-1 rounded-full border border-destructive bg-destructive/10 px-2 py-0.5 text-xs font-semibold text-destructive"
    >
      Emergency · {label} (ADS-B status)
    </span>
  );
}
