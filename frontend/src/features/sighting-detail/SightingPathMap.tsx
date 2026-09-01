/**
 * The sighting detail view's map: reuses `MapLibreMap` (rings/receiver
 * marker/WebGL-less degradation already handled there) and mounts
 * `SightingPathLayer` as its overlay child, the same composition
 * `AircraftLayer` uses on the Live Map. Centered on the receiver the app is
 * already tracking (`useMapConfigStore`, synced app-wide by `RootLayout`),
 * so the sighting's own path fits into the same picture the Live Map shows.
 */

import { getDefaultBasemap } from "@/features/map/basemaps";
import { MapLibreMap } from "@/features/map/MapLibreMap";
import { useMapConfigStore } from "@/features/map/store/useMapConfigStore";
import { SightingPathLayer } from "@/features/sighting-detail/SightingPathLayer";
import type { SightingPathPoint } from "@/lib/api/sightings";

export interface SightingPathMapProps {
  path: SightingPathPoint[];
}

export function SightingPathMap({ path }: SightingPathMapProps) {
  const config = useMapConfigStore((state) => state.config);
  const basemap = getDefaultBasemap();

  if (path.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center rounded-lg border border-border bg-secondary/30 text-sm text-muted-foreground">
        No path was recorded for this sighting (tracked without a position).
      </div>
    );
  }

  return (
    <MapLibreMap
      config={config}
      basemap={basemap}
      className="h-64 rounded-lg border border-border sm:h-80"
    >
      <SightingPathLayer path={path} />
    </MapLibreMap>
  );
}
