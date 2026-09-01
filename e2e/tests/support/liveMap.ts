/**
 * Shared helpers for the Live Map E2E flows (roadmap slice 020: demo-mode
 * live map, aircraft selection + detail).
 */

import { expect, type APIRequestContext, type Page } from "@playwright/test";

/** The subset of `GET /api/v1/aircraft/current`'s item shape (`docs/API.md`
 * §3.3) these flows actually read. */
export interface CurrentAircraft {
  icao: string;
  callsign: string | null;
  position: { lat: number; lon: number } | null;
  on_ground: boolean | null;
  ground_speed_kt: number | null;
  state: "live" | "stale";
}

interface CurrentAircraftResponse {
  items: CurrentAircraft[];
  total: number;
}

/** Fetches the live positioned-aircraft set straight from the REST API —
 * the same in-memory registry the WebSocket and the map layer read (`docs/
 * API.md` §3.3) — rather than through the UI, so the test has ground truth
 * independent of anything the map has gotten around to drawing yet. */
export async function fetchPositionedAircraft(
  request: APIRequestContext,
): Promise<CurrentAircraft[]> {
  const response = await request.get("/api/v1/aircraft/current?positioned=true");
  expect(response.ok(), `GET /api/v1/aircraft/current failed: ${response.status()}`).toBeTruthy();
  const body = (await response.json()) as CurrentAircraftResponse;
  return body.items;
}

/** The connection-status chip (`ConnectionStatusChip`): the one element on
 * the Live Map carrying `data-status`, so this selects it without a
 * dedicated test id. */
export function connectionStatusChip(page: Page) {
  return page.locator('[role="status"][data-status]');
}

/**
 * Waits for the demo scenario to be visibly live: the connection chip
 * reports `data-status="live"` (not just "connecting") **and** the
 * `live-aircraft-count` badge (`ConnectionStatusChip`) shows a non-zero
 * count — the user-visible proof that aircraft, not just the socket, have
 * arrived (roadmap slice 020 flow "demo-mode live map renders aircraft").
 * Demo mode staggers aircraft spawn ticks, so this can take longer than a
 * typical UI wait, hence the generous timeout.
 */
export async function waitForLiveAircraft(page: Page, timeoutMs = 45_000): Promise<void> {
  await expect(connectionStatusChip(page)).toHaveAttribute("data-status", "live", {
    timeout: timeoutMs,
  });
  await expect(page.getByTestId("live-aircraft-count")).toHaveText(/[1-9]\d* aircraft/, {
    timeout: timeoutMs,
  });
}

/** Mirrors `AIRCRAFT_SOURCE_ID` in
 * `frontend/src/features/map/aircraft/aircraftLayers.ts` — used only to
 * confirm the aircraft symbol layer has actually attached to the map
 * before a canvas click is attempted (icon registration + layer creation
 * happen asynchronously after the style loads). */
const AIRCRAFT_SOURCE_ID = "flightsite-aircraft";

/** Waits until the map's aircraft source (and therefore its symbol layer)
 * exists, via the `window.__flightsiteMap` E2E hook (`MapLibreMap.tsx`). */
export async function waitForAircraftLayer(page: Page, timeoutMs = 30_000): Promise<void> {
  await page.waitForFunction(
    (sourceId) => {
      const map = (window as unknown as { __flightsiteMap?: { getSource: (id: string) => unknown } })
        .__flightsiteMap;
      return !!map && !!map.getSource(sourceId);
    },
    AIRCRAFT_SOURCE_ID,
    { timeout: timeoutMs },
  );
}

/**
 * Clicks the map canvas at the pixel a positioned aircraft's real lat/lon
 * projects to, using the MapLibre instance's own `project()` (via the
 * `window.__flightsiteMap` E2E hook) rather than reimplementing Web
 * Mercator math in the test — the map's own projection is exact for
 * whatever center/zoom/bearing it currently holds, including after any
 * interaction.
 */
export async function clickAircraftOnMap(
  page: Page,
  aircraft: Pick<CurrentAircraft, "position">,
): Promise<void> {
  if (!aircraft.position) {
    throw new Error("clickAircraftOnMap requires a positioned aircraft");
  }
  const container = page.getByTestId("maplibre-container");
  const box = await container.boundingBox();
  if (!box) {
    throw new Error("maplibre-container has no bounding box (not visible?)");
  }

  const { lat, lon } = aircraft.position;
  const point = await page.evaluate(
    ({ lon, lat }) => {
      const map = (
        window as unknown as {
          __flightsiteMap?: { project: (lngLat: [number, number]) => { x: number; y: number } };
        }
      ).__flightsiteMap;
      if (!map) {
        return null;
      }
      const projected = map.project([lon, lat]);
      return { x: projected.x, y: projected.y };
    },
    { lon, lat },
  );
  if (!point) {
    throw new Error("window.__flightsiteMap was not set (map not mounted?)");
  }

  await page.mouse.click(box.x + point.x, box.y + point.y);
}

/** Flat-earth approximation of angular separation in degrees — plenty
 * accurate for "is anything else rendering right on top of this icon",
 * which only needs relative ordering, not a real distance. */
function approxDegreeDistance(
  a: { lat: number; lon: number },
  b: { lat: number; lon: number },
): number {
  const dLat = a.lat - b.lat;
  const dLon = (a.lon - b.lon) * Math.cos((a.lat * Math.PI) / 180);
  return Math.hypot(dLat, dLon);
}

/**
 * Picks an aircraft whose click target is unambiguous: the one with the
 * most space to its nearest neighbor, tie-broken by ground speed (slower
 * drifts less between the API fetch and the click landing).
 *
 * Isolation matters more than stationarity here — demo traffic parks
 * several grounded aircraft at the same airport (`backend/src/flightsite/
 * demo/roster.py`), which at this map's zoom can render close enough that
 * `queryRenderedFeatures` at a shared pixel returns whichever one painted
 * on top, not necessarily the one the test meant to click. A fast but
 * solitary aircraft moves a negligible fraction of the icon's own size in
 * the roughly one second between fetch and click, so it is a far safer
 * target than a stationary one with a neighbor at the same spot.
 *
 * `exclude` lets a caller retry against a different candidate after a
 * previous attempt's pick turned out ambiguous in practice.
 */
export function pickStableAircraft(
  items: CurrentAircraft[],
  exclude: ReadonlySet<string> = new Set(),
): CurrentAircraft {
  const positioned = items.filter(
    (item) => item.position !== null && item.state === "live" && !exclude.has(item.icao),
  );
  if (positioned.length === 0) {
    throw new Error("no positioned, live, non-excluded aircraft available to select");
  }

  const ranked = positioned
    .map((item) => {
      const others = positioned.filter((other) => other.icao !== item.icao);
      const nearestDistanceDeg =
        others.length > 0
          ? Math.min(
              ...others.map((other) => approxDegreeDistance(item.position!, other.position!)),
            )
          : Number.POSITIVE_INFINITY;
      return { item, nearestDistanceDeg };
    })
    .sort((a, b) => {
      if (a.nearestDistanceDeg !== b.nearestDistanceDeg) {
        return b.nearestDistanceDeg - a.nearestDistanceDeg;
      }
      return (a.item.ground_speed_kt ?? Infinity) - (b.item.ground_speed_kt ?? Infinity);
    });

  return ranked[0]!.item;
}
