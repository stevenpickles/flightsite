/**
 * The sighting detail view's reception-stats, records and route blocks —
 * three small `DetailSection`s co-located in one file since each is a
 * handful of `FieldRow`s and none is reused outside this page (unlike
 * `LifetimeSection`, which the Aircraft page's detail route also renders).
 */

import { DetailSection } from "@/features/aircraft-detail/components/DetailSection";
import { FieldRow } from "@/features/aircraft-detail/components/FieldRow";
import {
  formatAltitude,
  formatDistance,
  formatMessageCount,
  formatRssi,
} from "@/features/aircraft-detail/lib/format";
import type { RouteInfo } from "@/lib/api/live";
import type { ReceptionStats, SightingRecords } from "@/lib/api/sightings";
import type { UnitSystem } from "@/lib/api/config";

function formatPercent(value: number | null): string | null {
  if (value === null) {
    return null;
  }
  return `${value.toFixed(1)}%`;
}

export interface SightingReceptionSectionProps {
  reception: ReceptionStats;
}

export function SightingReceptionSection({
  reception,
}: SightingReceptionSectionProps) {
  return (
    <DetailSection title="Reception">
      <FieldRow
        label="Peak signal"
        value={formatRssi(reception.rssi_peak_db)}
      />
      <FieldRow
        label="Average signal"
        value={formatRssi(reception.rssi_avg_db)}
      />
      <FieldRow
        label="Weakest signal"
        value={formatRssi(reception.rssi_min_db)}
      />
      <FieldRow
        label="Messages"
        value={formatMessageCount(reception.message_count)}
      />
      <FieldRow
        label="Position reports"
        value={formatMessageCount(reception.position_count)}
      />
      <FieldRow
        label="Time with a position"
        value={formatPercent(reception.pct_with_position)}
      />
    </DetailSection>
  );
}

export interface SightingRecordsSectionProps {
  records: SightingRecords;
  units: UnitSystem;
}

export function SightingRecordsSection({
  records,
  units,
}: SightingRecordsSectionProps) {
  return (
    <DetailSection title="Records">
      <FieldRow
        label="Closest approach"
        value={formatDistance(records.closest_approach_nm, units)}
      />
      <FieldRow
        label="Maximum range"
        value={formatDistance(records.max_range_nm, units)}
      />
      <FieldRow
        label="Lowest altitude"
        value={formatAltitude(records.lowest_altitude_ft, units)}
      />
      <FieldRow
        label="Highest altitude"
        value={formatAltitude(records.highest_altitude_ft, units)}
      />
    </DetailSection>
  );
}

export interface SightingRouteSectionProps {
  route: RouteInfo;
  provenanceSource?: string;
}

export function SightingRouteSection({
  route,
  provenanceSource,
}: SightingRouteSectionProps) {
  if (route.origin === null && route.destination === null) {
    return null;
  }
  return (
    <DetailSection title="Route">
      <FieldRow
        label="Origin"
        value={route.origin}
        provenanceSource={provenanceSource}
      />
      <FieldRow
        label="Destination"
        value={route.destination}
        provenanceSource={provenanceSource}
      />
    </DetailSection>
  );
}
