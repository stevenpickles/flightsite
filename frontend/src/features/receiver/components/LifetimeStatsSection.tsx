/** SPEC §63 lifetime statistics section (roadmap slice 034), since T0 where
 * possible — `GET /api/v1/receiver/lifetime` (`docs/API.md` §3.8). */
import type { ReactNode } from "react";

import type { UnitSystem } from "@/lib/api/config";
import { useReceiverLifetimeStatsQuery } from "@/lib/api/receiverStats";
import {
  cardinalFromDegrees,
  formatCount,
  formatDistance,
  formatRatePerSec,
  formatReceiverLocalDate,
} from "@/features/receiver/lib/format";

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-border py-2 text-sm last:border-b-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium tabular-nums">{value}</span>
    </div>
  );
}

export interface LifetimeStatsSectionProps {
  units: UnitSystem;
  timezone: string;
}

export function LifetimeStatsSection({
  units,
  timezone,
}: LifetimeStatsSectionProps) {
  const { data, isLoading, isError } = useReceiverLifetimeStatsQuery();

  if (isLoading) {
    return (
      <p className="text-sm text-muted-foreground">
        Loading lifetime statistics…
      </p>
    );
  }

  if (isError || data === undefined) {
    return (
      <p className="text-sm text-destructive">
        Could not load lifetime statistics.
      </p>
    );
  }

  const maxRange = data.max_range;
  const busiestDay = data.busiest_day;
  const mostFrequent = data.most_frequent_aircraft;

  return (
    <section
      aria-labelledby="receiver-lifetime-heading"
      className="rounded-lg border border-border bg-card p-4 text-card-foreground"
    >
      <h3 id="receiver-lifetime-heading" className="mb-2 text-sm font-medium">
        Lifetime statistics
        {data.since !== null && (
          <span className="ml-2 font-normal text-muted-foreground">
            since {formatReceiverLocalDate(data.since, timezone)}
          </span>
        )}
      </h3>
      <div className="grid gap-x-6 sm:grid-cols-2">
        <div>
          <Row
            label="Unique aircraft"
            value={formatCount(data.unique_aircraft)}
          />
          <Row
            label="Total sightings"
            value={formatCount(data.total_sightings)}
          />
          <Row
            label="Total positions"
            value={formatCount(data.total_positions)}
          />
          <Row
            label="Total messages"
            value={formatCount(data.total_messages)}
          />
          <Row
            label="Highest message rate"
            value={formatRatePerSec(data.peak_message_rate_per_sec, "msg")}
          />
          <Row
            label="Highest position rate"
            value={formatRatePerSec(data.peak_position_rate_per_sec, "pos")}
          />
        </div>
        <div>
          <Row
            label="Maximum detection distance"
            value={
              maxRange === null
                ? "—"
                : `${formatDistance(maxRange.nm, units)} (${cardinalFromDegrees(maxRange.bearing_deg)})`
            }
          />
          <Row
            label="Highest simultaneous aircraft"
            value={formatCount(data.max_simultaneous_aircraft)}
          />
          <Row
            label="Busiest day"
            value={
              busiestDay === null
                ? "—"
                : `${busiestDay.day} (${formatCount(busiestDay.message_count)} msgs)`
            }
          />
          <Row
            label="Most frequently seen aircraft"
            value={
              mostFrequent === null
                ? "—"
                : `${mostFrequent.registration ?? mostFrequent.icao.toUpperCase()} (${formatCount(mostFrequent.sighting_count)} sightings)`
            }
          />
          <Row
            label="Common type"
            value={
              data.common_type === null
                ? "—"
                : `${data.common_type.value} (${formatCount(data.common_type.aircraft_count)})`
            }
          />
          <Row
            label="Common operator"
            value={
              data.common_operator === null
                ? "—"
                : `${data.common_operator.value} (${formatCount(data.common_operator.aircraft_count)})`
            }
          />
        </div>
      </div>
    </section>
  );
}
