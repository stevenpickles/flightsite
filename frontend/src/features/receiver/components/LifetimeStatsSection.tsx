/** SPEC §63 lifetime statistics section (roadmap slice 034), since T0 where
 * possible — `GET /api/v1/receiver/lifetime` (`docs/API.md` §3.8). */
import type { ReactNode } from "react";

import type { UnitSystem } from "@/lib/api/config";
import { useReceiverLifetimeStatsQuery } from "@/lib/api/receiverStats";
import { Button } from "@/components/ui/button";
import {
  formatCalendarDay,
  formatSightings,
} from "@/features/analytics/lib/format";
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
  const { data, isLoading, isError, refetch } = useReceiverLifetimeStatsQuery();

  if (isLoading) {
    return (
      <p className="text-sm text-muted-foreground">
        Loading lifetime statistics…
      </p>
    );
  }

  if (isError || data === undefined) {
    return (
      <div className="flex items-center gap-3">
        <p role="alert" className="text-sm text-destructive">
          Could not load lifetime statistics.
        </p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => void refetch()}
        >
          Retry
        </Button>
      </div>
    );
  }

  const maxRange = data.max_range;
  const busiestDay = data.busiest_day;
  const mostFrequent = data.most_frequent_aircraft;
  // R3-10: when every lifetime sighting total equals the unique-aircraft
  // count, every aircraft has been seen exactly once — "most frequently
  // seen" then names an arbitrary tie-break as if it were a record, which
  // reads as more meaningful than it is. (The reverse can never happen: a
  // total below the unique count is impossible, since each aircraft
  // contributes at least one sighting to be counted as seen at all.)
  const allAircraftTiedAtOneSighting =
    data.unique_aircraft > 0 && data.total_sightings === data.unique_aircraft;

  return (
    <section
      aria-labelledby="receiver-lifetime-heading"
      className="rounded-lg border border-border bg-card p-4 text-card-foreground"
    >
      {/* h2, not h3 (R3-14): this section is a sibling of the "Charts" h2
          above it, not a subsection of anything, so it belongs at the same
          level — h3 here made the page's heading outline skip straight from
          h2 to h3 with nothing in between. */}
      <h2 id="receiver-lifetime-heading" className="mb-2 text-sm font-medium">
        {/* A trailing space (R3-14): without it, "Lifetime statistics" and
            "since ..." concatenate into one word in the accessible name —
            `ml-2`'s visual margin does not add a text-content space. */}
        Lifetime statistics{" "}
        {data.since !== null && (
          <span className="ml-2 font-normal text-muted-foreground">
            since {formatReceiverLocalDate(data.since, timezone)}
          </span>
        )}
      </h2>
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
                : `${formatCalendarDay(busiestDay.day)} (${formatCount(busiestDay.message_count)} msgs)`
            }
          />
          <Row
            label="Most frequently seen aircraft"
            value={
              allAircraftTiedAtOneSighting
                ? `${formatCount(data.unique_aircraft)} aircraft tied at 1 sighting`
                : mostFrequent === null
                  ? "—"
                  : `${mostFrequent.registration ?? mostFrequent.icao.toUpperCase()} (${formatSightings(mostFrequent.sighting_count)})`
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
            label="Common model"
            value={
              data.common_model === null
                ? "—"
                : `${data.common_model.value} (${formatCount(data.common_model.aircraft_count)})`
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
