/**
 * Shared helpers for the history-backed pages — Aircraft and Sightings
 * (roadmap slice 046, `docs/TEST_STRATEGY.md` §4).
 *
 * Why these pages need a wait the Live Map ones do not
 * ---------------------------------------------------
 * The Live Map reads the in-memory live registry, which is populated the
 * moment the demo adapter emits a frame. These two pages read *persisted*
 * history instead, which arrives by a different route: ingestion never blocks
 * on the database (`CLAUDE.md`, ADR-0002), so a sighting reaches SQLite only
 * once the write-behind persistence worker has flushed it. Between the first
 * demo aircraft appearing and the first row existing in `/api/v1/aircraft`
 * there is therefore a real, load-dependent gap.
 *
 * The gap is closed by polling the API for the condition itself rather than
 * by waiting a fixed amount of time (`docs/TEST_STRATEGY.md` §3: no
 * `sleep()`-based timing). `expect.poll` retries a real predicate and stops
 * the instant it holds, so the flows below are as fast as the stack allows
 * and still correct on a slow, cold container.
 *
 * These helpers return the API's own answer so a spec can assert the UI
 * against ground truth from the same source the UI reads, exactly as
 * `liveMap.ts`'s `fetchPositionedAircraft` does for the live picture.
 */

import { expect, type APIRequestContext } from "@playwright/test";

/** The subset of `GET /api/v1/aircraft`'s row shape (`docs/API.md` §3.5)
 * these flows actually read. */
export interface AircraftListRow {
  icao: string;
  registration: string | null;
  aircraft_type: string | null;
  operator: string | null;
  first_seen: string;
  last_seen: string;
  sighting_count: number;
}

interface AircraftListResponse {
  items: AircraftListRow[];
  total: number | null;
}

/** The subset of `GET /api/v1/sightings`'s row shape (`docs/API.md` §3.6)
 * these flows actually read. */
export interface SightingRow {
  id: number;
  icao: string;
  callsign: string | null;
  registration: string | null;
  started_at: string;
  ended_at: string | null;
  position_count: number;
}

interface SightingListResponse {
  items: SightingRow[];
  total: number | null;
}

/** How long to give the persistence worker to produce the first history row.
 * Generous rather than tight: the budget covers a cold container's first
 * flush, and a healthy stack satisfies the predicate long before it. */
const PERSIST_TIMEOUT_MS = 90_000;

/**
 * Waits until at least one aircraft has been persisted, and returns that
 * first page of rows.
 *
 * The returned rows are ground truth for the assertions in
 * `07-aircraft-page.spec.ts`: the page under test must show what this says
 * exists, so the test never asserts against numbers the UI itself invented.
 */
export async function waitForPersistedAircraft(
  request: APIRequestContext,
  timeoutMs = PERSIST_TIMEOUT_MS,
): Promise<AircraftListRow[]> {
  let items: AircraftListRow[] = [];
  await expect
    .poll(
      async () => {
        const response = await request.get(
          "/api/v1/aircraft?limit=50&offset=0&sort=last_seen&order=desc",
        );
        if (!response.ok()) {
          return 0;
        }
        const body = (await response.json()) as AircraftListResponse;
        items = body.items;
        return items.length;
      },
      {
        timeout: timeoutMs,
        message:
          "no aircraft were ever persisted — demo traffic never reached SQLite",
      },
    )
    .toBeGreaterThan(0);
  return items;
}

/**
 * Waits until at least one sighting has been persisted, and returns that
 * first page of rows (newest first, the page's own default ordering).
 */
export async function waitForPersistedSightings(
  request: APIRequestContext,
  timeoutMs = PERSIST_TIMEOUT_MS,
): Promise<SightingRow[]> {
  let items: SightingRow[] = [];
  await expect
    .poll(
      async () => {
        const response = await request.get(
          "/api/v1/sightings?limit=50&offset=0&sort=started_at&order=desc",
        );
        if (!response.ok()) {
          return 0;
        }
        const body = (await response.json()) as SightingListResponse;
        items = body.items;
        return items.length;
      },
      {
        timeout: timeoutMs,
        message:
          "no sightings were ever persisted — demo traffic never reached SQLite",
      },
    )
    .toBeGreaterThan(0);
  return items;
}

/**
 * Picks the aircraft with the most sightings on record.
 *
 * Used as the ICAO-filter subject on the Sightings page: whichever aircraft
 * has the richest history is the one whose filtered result is least likely to
 * be a single row, which makes "the filter narrowed to exactly this aircraft"
 * a meaningful assertion rather than a coincidence.
 */
export function pickBusiestAircraft(
  rows: readonly AircraftListRow[],
): AircraftListRow {
  if (rows.length === 0) {
    throw new Error("pickBusiestAircraft requires at least one aircraft");
  }
  return rows.reduce((best, row) =>
    row.sighting_count > best.sighting_count ? row : best,
  );
}
