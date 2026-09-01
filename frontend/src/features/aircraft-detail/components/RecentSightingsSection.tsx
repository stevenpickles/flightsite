/**
 * The aircraft detail page's "recent sightings" list (roadmap slice 030,
 * item 4 — the per-aircraft log deferred from slice 029). A small, most
 * recent-first slice of `GET /api/v1/aircraft/{icao}/sightings`, each row
 * linking into its sighting detail; "View all" hands off to the Sightings
 * page pre-filtered to this aircraft.
 */

import { Link } from "react-router-dom";

import { DetailSection } from "@/features/aircraft-detail/components/DetailSection";
import { UnknownValue } from "@/features/aircraft-detail/components/UnknownValue";
import { formatReceiverLocalDateTime } from "@/features/aircraft-detail/lib/format";
import { formatSightingDuration } from "@/features/sightings/lib/format";
import { useAircraftSightingsQuery } from "@/lib/api/sightings";

const RECENT_LIMIT = 5;

export interface RecentSightingsSectionProps {
  icao: string;
  timezone: string;
}

export function RecentSightingsSection({
  icao,
  timezone,
}: RecentSightingsSectionProps) {
  const query = useAircraftSightingsQuery({
    icao,
    limit: RECENT_LIMIT,
    offset: 0,
  });

  return (
    <DetailSection title="Recent sightings">
      {query.isPending ? (
        <p className="py-2 text-sm text-muted-foreground">Loading…</p>
      ) : query.isError ? (
        <p className="py-2 text-sm text-destructive">
          Could not load recent sightings: {query.error.message}
        </p>
      ) : query.data.items.length === 0 ? (
        <p className="py-2 text-sm text-muted-foreground">
          No sightings recorded yet.
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-border/60">
          {query.data.items.map((sighting) => (
            <li
              key={sighting.id}
              className="flex items-center justify-between gap-3 py-1.5 text-sm"
            >
              <Link
                to={`/sightings/${sighting.id}`}
                className="text-accent hover:underline"
              >
                {formatReceiverLocalDateTime(sighting.started_at, timezone)}
              </Link>
              <span className="text-xs text-muted-foreground">
                {sighting.ended_at === null ? (
                  "Ongoing"
                ) : sighting.duration_s === null ? (
                  <UnknownValue />
                ) : (
                  formatSightingDuration(sighting.duration_s)
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      <Link
        to={`/sightings?icao=${icao}`}
        className="mt-2 inline-block text-xs text-accent hover:underline"
      >
        View all sightings for this aircraft →
      </Link>
    </DetailSection>
  );
}
