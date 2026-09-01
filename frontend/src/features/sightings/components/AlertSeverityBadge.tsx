/**
 * Alert/interesting-status badge for the Sightings log and detail view
 * (SPEC §57's "alert/interesting status" column, §2.8's severity ladder).
 * Text-first per §80 (never color-only): the severity word itself is the
 * label, the border/text tint is a secondary cue. `max_alert_severity` is
 * `null` until slice 038 ever writes a value — callers simply render
 * nothing for a `null` severity.
 */

import type { AlertSeverity } from "@/lib/api/sightings";
import { cn } from "@/lib/utils";

const LABELS: Record<AlertSeverity, string> = {
  info: "Info",
  interesting: "Interesting",
  high: "High",
  critical: "Critical",
};

const TONE_CLASSES: Record<AlertSeverity, string> = {
  info: "border-border text-muted-foreground",
  interesting: "border-accent/60 text-accent",
  high: "border-amber-500/60 text-amber-600 dark:text-amber-400",
  critical: "border-destructive text-destructive",
};

export interface AlertSeverityBadgeProps {
  severity: AlertSeverity;
}

export function AlertSeverityBadge({ severity }: AlertSeverityBadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold",
        TONE_CLASSES[severity],
      )}
    >
      {LABELS[severity]}
    </span>
  );
}
