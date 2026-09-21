/**
 * The "History" section's real content: SPEC §53's lifetime record block,
 * unit-aware and receiver-local-time-aware. Used by the non-live detail
 * page (`GET /api/v1/aircraft/{icao}`'s `lifetime` block) — the live detail
 * panel links to that page instead of rendering this itself (roadmap slice
 * 029; see `AircraftDetailPanel`'s History section).
 */

import { DetailSection } from "@/features/aircraft-detail/components/DetailSection";
import { FieldRow } from "@/features/aircraft-detail/components/FieldRow";
import { ReceiverTime } from "@/features/aircraft-detail/components/ReceiverTime";
import {
  formatAltitude,
  formatDistance,
  formatDurationShort,
} from "@/features/aircraft-detail/lib/format";
import type { LifetimeRecord } from "@/lib/api/aircraft";
import type { UnitSystem } from "@/lib/api/config";

export interface LifetimeSectionProps {
  lifetime: LifetimeRecord;
  units: UnitSystem;
  timezone: string;
}

export function LifetimeSection({
  lifetime,
  units,
  timezone,
}: LifetimeSectionProps) {
  return (
    <DetailSection title="History">
      <FieldRow
        label="First seen"
        value={<ReceiverTime iso={lifetime.first_seen} timezone={timezone} />}
      />
      <FieldRow
        label="Last seen"
        value={<ReceiverTime iso={lifetime.last_seen} timezone={timezone} />}
      />
      <FieldRow
        label="Sighting count"
        value={String(lifetime.sighting_count)}
      />
      {/* The total now includes a sighting still in progress, so it no
       * longer reads `0s` for an aircraft that has been overhead for
       * sixteen minutes (review R2-02). When part of it is still accruing,
       * the row says how much — otherwise the number would quietly change
       * under a reader with no explanation. */}
      <FieldRow
        label="Cumulative observed time"
        value={
          <span>
            {formatDurationShort(lifetime.cumulative_duration_s * 1000)}
            {lifetime.open_sighting_elapsed_s !== null && (
              <span className="font-normal text-muted-foreground">
                {" · "}
                {formatDurationShort(
                  lifetime.open_sighting_elapsed_s * 1000,
                )}{" "}
                still running
              </span>
            )}
          </span>
        }
      />
      <FieldRow
        label="Closest approach"
        value={formatDistance(lifetime.closest_approach_nm, units)}
      />
      <FieldRow
        label="Farthest detection"
        value={formatDistance(lifetime.max_range_nm, units)}
      />
      <FieldRow
        label="Lowest altitude"
        value={formatAltitude(lifetime.lowest_altitude_ft, units)}
      />
      <FieldRow
        label="Highest altitude"
        value={formatAltitude(lifetime.highest_altitude_ft, units)}
      />
    </DetailSection>
  );
}
