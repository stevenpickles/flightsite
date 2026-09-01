/**
 * The active-alert section of the detail panel (SPEC §43/§46, roadmap slice
 * 039): what is matching against this aircraft right now, and why.
 *
 * Unlike {@link NearestAirportSection}, this section renders **only when
 * something is matching**. The two are different kinds of absent: a cruising
 * aircraft genuinely has a nearest-airport answer (*"nothing near"*) worth
 * stating, whereas an "Alerts: none" row on every ordinary airliner would be
 * a line of chrome on the overwhelming majority of aircraft and would make
 * the one that *is* alerting harder to spot, not easier.
 *
 * Every reason is listed, not just the first. The engine can stand more than
 * one match against a sighting — a military aircraft that is also on a
 * watchlist — and the panel is where a user goes to find out *which* rule
 * fired, so collapsing them to the most severe would discard the answer they
 * came for. They arrive most-severe-first, which is the order they render in.
 *
 * Severity is the shared {@link AlertSeverityBadge}, so the word "Critical"
 * carries the message and the tint is decoration (SPEC §80).
 */

import { DetailSection } from "@/features/aircraft-detail/components/DetailSection";
import { FieldRow } from "@/features/aircraft-detail/components/FieldRow";
import { AlertSeverityBadge } from "@/features/sightings/components/AlertSeverityBadge";
import type { InterestingMatch } from "@/lib/api/live";

export interface InterestingSectionProps {
  interesting: InterestingMatch | null;
}

export function InterestingSection({ interesting }: InterestingSectionProps) {
  if (interesting === null) {
    return null;
  }

  return (
    <DetailSection title="Interesting">
      <FieldRow
        label="Severity"
        value={<AlertSeverityBadge severity={interesting.severity} />}
      />
      <FieldRow
        label={interesting.reasons.length === 1 ? "Reason" : "Reasons"}
        value={
          interesting.reasons.length === 0 ? null : (
            <span
              data-testid="interesting-reasons"
              className="flex flex-col items-end gap-0.5"
            >
              {interesting.reasons.map((reason) => (
                <span key={reason}>{reason}</span>
              ))}
            </span>
          )
        }
      />
    </DetailSection>
  );
}
