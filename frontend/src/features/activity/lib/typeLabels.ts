/**
 * Short names for the event *kinds*, for the filter chips.
 *
 * Distinct from `describeActivityEvent`, which names one event ("New aircraft
 * type: B738") using its payload. A chip names the category, has room for two
 * or three words, and must read the same whether or not any such event exists
 * yet — so the two are separate maps rather than one function asked to do both
 * jobs at two different lengths.
 */

import type { ActivityEventType } from "@/lib/api/activity";

const LABELS: Record<ActivityEventType, string> = {
  alert_triggered: "Alerts",
  first_ever_aircraft: "First seen",
  new_type: "New types",
  range_record: "Range records",
  receiver_record: "Records",
  emergency_squawk: "Emergencies",
  receiver_offline: "Offline",
  receiver_restored: "Restored",
  metadata_updated: "Metadata",
  milestone: "Milestones",
};

/** The chip label for an event type; falls back to the slug itself for a
 * type this build predates, which is still better than an empty chip. */
export function describeActivityType(type: ActivityEventType): string {
  return LABELS[type] ?? type;
}
