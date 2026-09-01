/**
 * "Locally rare aircraft/type information" plus the window's never-seen-
 * before total (SPEC §58, `GET /api/v1/analytics/rarity`) — two compact
 * tables rather than a chart: rarity is a short, specific list of airframes
 * and types, exactly the case where a table reads faster than a plot.
 * Rare-aircraft rows link to the aircraft detail route (roadmap slice 029);
 * type designators have no detail route in this app, so rare-type rows stay
 * plain text.
 */
import { Link } from "react-router-dom";

import type {
  AnalyticsAircraftRow,
  AnalyticsRareType,
  AnalyticsWindow,
} from "@/lib/api/analytics";

import { AnalyticsCard } from "@/features/analytics/components/AnalyticsCard";
import { humanizeSlug } from "@/features/analytics/lib/format";

export interface RarityListsCardProps {
  window?: AnalyticsWindow;
  neverSeenBefore: number;
  rareMaxSightings: number;
  rareAircraft: AnalyticsAircraftRow[];
  rareTypes: AnalyticsRareType[];
  isLoading: boolean;
  error?: string;
}

export function RarityListsCard({
  window,
  neverSeenBefore,
  rareMaxSightings,
  rareAircraft,
  rareTypes,
  isLoading,
  error,
}: RarityListsCardProps) {
  return (
    <AnalyticsCard
      title="Locally rare"
      window={window}
      isLoading={isLoading}
      error={error}
    >
      <div className="flex flex-col gap-4">
        <p className="text-sm text-foreground">
          <span className="font-semibold">{neverSeenBefore}</span> aircraft
          never seen before this window.
        </p>

        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Rare aircraft{" "}
            <span className="normal-case">
              (lifetime sightings ≤ {rareMaxSightings})
            </span>
          </h3>
          {rareAircraft.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No rare aircraft in this window.
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <th scope="col" className="py-1 pr-2 font-semibold">
                    Aircraft
                  </th>
                  <th scope="col" className="py-1 pr-2 font-semibold">
                    Type
                  </th>
                  <th scope="col" className="py-1 text-right font-semibold">
                    Sightings
                  </th>
                </tr>
              </thead>
              <tbody>
                {rareAircraft.map((row) => (
                  <tr key={row.icao} className="border-t border-border/60">
                    <td className="py-1 pr-2">
                      <Link
                        to={`/aircraft/${row.icao}`}
                        className="font-medium text-accent hover:underline"
                      >
                        {row.registration ?? row.icao.toUpperCase()}
                      </Link>
                    </td>
                    <td className="py-1 pr-2 text-muted-foreground">
                      {row.type ?? "Unknown"}
                    </td>
                    <td className="py-1 text-right">{row.sightings}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div>
          <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Rare types
          </h3>
          {rareTypes.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No rare types in this window.
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <th scope="col" className="py-1 pr-2 font-semibold">
                    Type
                  </th>
                  <th
                    scope="col"
                    className="py-1 pr-2 text-right font-semibold"
                  >
                    Aircraft
                  </th>
                  <th scope="col" className="py-1 text-right font-semibold">
                    Sightings
                  </th>
                </tr>
              </thead>
              <tbody>
                {rareTypes.map((row) => (
                  <tr key={row.type} className="border-t border-border/60">
                    <td className="py-1 pr-2">{humanizeSlug(row.type)}</td>
                    <td className="py-1 pr-2 text-right">
                      {row.unique_aircraft}
                    </td>
                    <td className="py-1 text-right">{row.total_sightings}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </AnalyticsCard>
  );
}
