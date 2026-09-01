/**
 * Typed clients for the aviation-overlay endpoints (roadmap slice 028) —
 * `GET /api/v1/airports` (airport markers, from the slice 027 dataset) and
 * `GET /api/v1/airspace` (the user-supplied overlay, `docs/adr/0012-airspace-
 * data-source.md`). Both return a plain GeoJSON `FeatureCollection`, handed
 * to a MapLibre source largely as-is — see `features/map/overlays/`.
 */
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import type { FeatureCollection } from "geojson";

/** Mirrors the backend's `AirportSizeClass` (`flightsite.airports.overlay`)
 * exactly — the `min_size` query param and the `size_class` GeoJSON
 * property both use this vocabulary. */
export type AirportSizeClass = "large" | "medium" | "small" | "heliport";

const AIRPORTS_PATH = "/api/v1/airports";
const AIRSPACE_PATH = "/api/v1/airspace";

async function fetchFeatureCollection(
  path: string,
): Promise<FeatureCollection> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }
  return (await response.json()) as FeatureCollection;
}

export interface AirportsQueryParams {
  /** `west,south,east,north` in decimal degrees. Omitted queries the whole
   * dataset (capped, largest-first) rather than a viewport. */
  bbox?: string;
  /** Smallest size class to include. Omitted includes every size class. */
  minSize?: AirportSizeClass;
}

function airportsPath({ bbox, minSize }: AirportsQueryParams): string {
  const query = new URLSearchParams();
  if (bbox !== undefined) {
    query.set("bbox", bbox);
  }
  if (minSize !== undefined) {
    query.set("min_size", minSize);
  }
  const search = query.toString();
  return search ? `${AIRPORTS_PATH}?${search}` : AIRPORTS_PATH;
}

export function getAirports(
  params: AirportsQueryParams,
): Promise<FeatureCollection> {
  return fetchFeatureCollection(airportsPath(params));
}

export function getAirspace(): Promise<FeatureCollection> {
  return fetchFeatureCollection(AIRSPACE_PATH);
}

export const overlayQueryKeys = {
  airports: (params: AirportsQueryParams) =>
    ["overlays", "airports", params] as const,
  airspace: () => ["overlays", "airspace"] as const,
};

/** One viewport's worth of airport markers. `enabled: false` (passed by the
 * caller — see `overlays/airportDensity.ts`'s `minSizeForZoom`) skips the
 * request entirely for a zoom below every size class's threshold, where
 * nothing would be drawn anyway. `placeholderData` keeps the previous
 * viewport's markers on screen while a pan settles rather than flashing to
 * empty on every debounced refetch. */
export function useAirportsQuery(
  params: AirportsQueryParams,
  enabled: boolean,
): UseQueryResult<FeatureCollection> {
  return useQuery({
    queryKey: overlayQueryKeys.airports(params),
    queryFn: () => getAirports(params),
    enabled,
    placeholderData: (previous) => previous,
  });
}

/** The user-supplied airspace overlay. `GET /api/v1/airspace` always answers
 * with the whole file (or an empty collection), so this is fetched once per
 * mount rather than per viewport. A long `staleTime`: the file changes only
 * when a user edits it on disk, never on a live cadence. */
export function useAirspaceQuery(): UseQueryResult<FeatureCollection> {
  return useQuery({
    queryKey: overlayQueryKeys.airspace(),
    queryFn: getAirspace,
    staleTime: 5 * 60 * 1000,
  });
}
