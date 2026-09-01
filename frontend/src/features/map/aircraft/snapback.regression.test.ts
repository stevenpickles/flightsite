/**
 * Regression: markers crept forward then teleported back (issue #119).
 *
 * Driven through the real store rather than hand-built records, because the
 * defect lived in the seam between the two: `displayPosition` dead-reckoned
 * from `receivedAt`, which every delta refreshed, while `aircraft.position`
 * only changed when a new CPR fix decoded — every 2-10 s for a distant
 * aircraft. Each no-new-fix delta reset elapsed time to zero and snapped the
 * marker back to the stale fix. A unit test over a fabricated record cannot
 * see that; only applying a real delta sequence can.
 */

import { beforeEach, describe, expect, it } from "vitest";

import { displayPosition } from "@/features/map/aircraft/interpolation";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { makeAircraft } from "@/test/liveAircraftFixtures";

const T0 = 1_700_000_000_000;
const ICAO = "aaaaaa";

/** Due north at 360 kt: 0.1 nm a second, or 1/600 of a degree of latitude. */
const DEGREES_PER_SECOND = 0.1 / 60;

function inbound(overrides = {}) {
  return makeAircraft({
    icao: ICAO,
    position: { lat: 0, lon: 0 },
    track_deg: 0,
    ground_speed_kt: 360,
    ...overrides,
  });
}

function drawnLat(now: number): number {
  const record = useLiveAircraftStore.getState().aircraft[ICAO];
  if (!record) {
    throw new Error(`${ICAO} is not in the store`);
  }
  const position = displayPosition(record, now);
  if (!position) {
    throw new Error(`${ICAO} has no drawable position`);
  }
  return position.lat;
}

beforeEach(() => {
  useLiveAircraftStore.getState().reset();
  useLiveAircraftStore
    .getState()
    .applySnapshot({ aircraft: [inbound()], receiver: null }, T0);
});

describe("live map motion across deltas that do not move the fix", () => {
  it("keeps projecting when a delta carries the same fix", () => {
    // Two seconds on, the receiver has re-reported the aircraft twice with a
    // fresh RSSI but no new position decode.
    for (const tick of [1000, 2000]) {
      useLiveAircraftStore.getState().applyDelta(
        {
          updated: [inbound({ rssi_db: -20 - tick / 1000 })],
          stale: [],
          removed: [],
        },
        T0 + tick,
      );
    }

    expect(drawnLat(T0 + 2000)).toBeCloseTo(2 * DEGREES_PER_SECOND, 9);
  });

  it("never draws the aircraft behind where it was a moment earlier", () => {
    // The visible symptom: sample the drawn latitude either side of each
    // delta. A backwards step anywhere in the sequence is the teleport.
    let previous = drawnLat(T0);
    for (let tick = 250; tick <= 8000; tick += 250) {
      const now = T0 + tick;
      if (tick % 1000 === 0) {
        // A delta lands on the second, repeating the last known fix.
        useLiveAircraftStore
          .getState()
          .applyDelta(
            { updated: [inbound({ rssi_db: -20 })], stale: [], removed: [] },
            now,
          );
      }
      const current = drawnLat(now);
      expect(
        current,
        `drew backwards at +${tick} ms: ${current} < ${previous}`,
      ).toBeGreaterThanOrEqual(previous);
      previous = current;
    }
  });

  it("projects continuously across a realistic 8 s gap between fixes", () => {
    // Distant aircraft decode a position every 2-10 s while still sending
    // Mode S every second. The marker must keep moving the whole way.
    for (let tick = 1000; tick <= 8000; tick += 1000) {
      useLiveAircraftStore
        .getState()
        .applyDelta(
          { updated: [inbound({ rssi_db: -21 })], stale: [], removed: [] },
          T0 + tick,
        );
    }

    expect(drawnLat(T0 + 8000)).toBeCloseTo(8 * DEGREES_PER_SECOND, 9);
  });

  it("re-anchors when a genuinely new fix arrives", () => {
    useLiveAircraftStore.getState().applyDelta(
      {
        updated: [inbound({ position: { lat: 0.05, lon: 0 } })],
        stale: [],
        removed: [],
      },
      T0 + 3000,
    );

    // Elapsed restarts from the new fix, so one second on the marker is one
    // second's travel past it — not four seconds past the old one.
    expect(drawnLat(T0 + 4000)).toBeCloseTo(0.05 + DEGREES_PER_SECOND, 9);
  });

  it("keeps the anchor across a snapshot that repeats the same fix", () => {
    // Snapshots rebuild the picture wholesale; an aircraft that survives one
    // must not have its projection restarted.
    useLiveAircraftStore
      .getState()
      .applySnapshot({ aircraft: [inbound()], receiver: null }, T0 + 2000);

    expect(drawnLat(T0 + 2000)).toBeCloseTo(2 * DEGREES_PER_SECOND, 9);
  });

  it("freezes in place rather than rewinding when the stream dies", () => {
    // No delta ever arrives. The marker may coast briefly, then must hold —
    // and must never jump back to the fix it started from.
    const coasted = drawnLat(T0 + 60_000);
    expect(coasted).toBeGreaterThan(0);
    expect(drawnLat(T0 + 600_000)).toBe(coasted);
  });
});
