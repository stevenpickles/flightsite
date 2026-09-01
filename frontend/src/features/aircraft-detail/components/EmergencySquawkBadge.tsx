/**
 * Emergency squawk badge (scope item 2, SPEC §47): 7500/7600/7700 are
 * "prominent events... visually emphasized" — this renders whenever the
 * decoded squawk is one of the three universal codes, independent of
 * whether the separate `emergency` field also flags it, so the badge never
 * depends on one field having been populated correctly to show the other.
 * Text-first per §80 (never color-only): the code and its plain-language
 * meaning are the label itself, not implied by a background color alone.
 */

import { EMERGENCY_SQUAWK_LABELS } from "@/features/aircraft-detail/lib/format";

export interface EmergencySquawkBadgeProps {
  squawk: string;
}

export function EmergencySquawkBadge({ squawk }: EmergencySquawkBadgeProps) {
  const meaning = EMERGENCY_SQUAWK_LABELS[squawk] ?? "Emergency";
  return (
    <span
      role="status"
      className="inline-flex items-center gap-1 rounded-full border border-destructive bg-destructive/10 px-2 py-0.5 text-xs font-semibold text-destructive"
    >
      Emergency · {squawk} ({meaning})
    </span>
  );
}
