/**
 * Typed icons and severity tone for the activity feed, mirroring the
 * `SightingEventsTimeline` idiom: one `Record` at module scope so a row's
 * icon is a lookup rather than a branch, and a partial tone map so only the
 * events that genuinely need colour get any.
 *
 * The `Record` is total over `ActivityEventType`, including the two phase-6
 * types no producer emits yet — TypeScript enforces that, which is exactly
 * the point: adding a type to the vocabulary in `lib/api/activity.ts` fails
 * the build here until the feed knows how to draw it.
 */

import {
  BellRing,
  CircleCheckBig,
  DatabaseBackup,
  type LucideIcon,
  Plane,
  Radar,
  Sparkles,
  TriangleAlert,
  Trophy,
  WifiOff,
} from "lucide-react";

import type { ActivityEventType } from "@/lib/api/activity";

export const ACTIVITY_ICONS: Record<ActivityEventType, LucideIcon> = {
  alert_triggered: BellRing,
  first_ever_aircraft: Plane,
  new_type: Sparkles,
  range_record: Radar,
  receiver_record: Trophy,
  emergency_squawk: TriangleAlert,
  receiver_offline: WifiOff,
  receiver_restored: CircleCheckBig,
  metadata_updated: DatabaseBackup,
  milestone: Trophy,
};

/**
 * Colour by §2.8 severity rather than by type.
 *
 * Severity is the backend's own judgement of how much a thing matters — an
 * outage is `high`, a record is `interesting`, a routine metadata import is
 * `info` — so keying the tone off it means the feed emphasises what the
 * producer meant to emphasise, and a new event type inherits sensible colour
 * without this map being touched. `info` is deliberately absent: the default
 * muted tone is the right one for most of the feed, and colouring everything
 * would mean colouring nothing.
 */
export const SEVERITY_TONE: Partial<Record<string, string>> = {
  interesting: "text-amber-600 dark:text-amber-400",
  high: "text-destructive",
  critical: "text-destructive",
};

/** The icon tone for one event's severity, defaulting to the muted one. */
export function toneForSeverity(severity: string): string {
  return SEVERITY_TONE[severity] ?? "text-muted-foreground";
}
