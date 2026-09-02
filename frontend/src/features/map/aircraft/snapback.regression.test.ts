/**
 * Regression: markers crept forward then teleported back (issues #119, #144).
 *
 * Driven through the real store rather than hand-built records, because the
 * defect lived in the seam between the two: `displayPosition` dead-reckoned
 * from `receivedAt`, which every delta refreshed, while `aircraft.position`
 * only changed when a new CPR fix decoded — every 2-10 s for a distant
 * aircraft. Each no-new-fix delta reset elapsed time to zero and snapped the
 * marker back to the stale fix. A unit test over a fabricated record cannot
 * see that; only applying a real delta sequence can.
 *
 * Issue #144 is the same symptom from the residue that fix left: the anchor was
 * still late by the fix's own decode age, so a *genuine* new fix landed behind
 * the projection running from the last one and stepped the marker back. The
 * first block below pins the #119 behaviour with `seen_pos_s: 0`, which must
 * stay bit-for-bit what it was; the second drives the same seam with the
 * nonzero ages a distant aircraft actually reports.
 */

import { beforeEach, describe, expect, it } from "vitest";

import { displayPosition } from "@/features/map/aircraft/interpolation";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import type { LiveAircraft } from "@/lib/api/live";
import { makeAircraft } from "@/test/liveAircraftFixtures";

const T0 = 1_700_000_000_000;
const ICAO = "aaaaaa";

/** Due north at 360 kt: 0.1 nm a second, or 1/600 of a degree of latitude. */
const DEGREES_PER_SECOND = 0.1 / 60;

/** The #119 scenario's aircraft: a reported age of zero, so every anchor here
 * is the arrival instant and the expectations below are the pre-#144 ones
 * unchanged. */
function inbound(overrides: Partial<LiveAircraft> = {}) {
  return makeAircraft({
    icao: ICAO,
    position: { lat: 0, lon: 0 },
    track_deg: 0,
    ground_speed_kt: 360,
    seen_pos_s: 0,
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

/**
 * Issue #144, modelled as the receiver and the network actually behave.
 *
 * A CPR fix is measured at some true instant, read by a backend poll some time
 * later — that gap is what the frame reports as `seen_pos_s` — and reaches the
 * browser after a further transport delay the frame says nothing about. The
 * decode gap varies fix by fix; the transport delay is shared by every frame
 * alike. Back-dating cancels the part that varies, which is the whole claim:
 * what is left is a constant lag no client-side arithmetic could remove.
 */
describe("live map motion when fixes arrive already aged", () => {
  /** The delay every frame shares: poll to socket to browser. Constant, so it
   * cannot be recovered from the data and does not need to be. */
  const TRANSPORT_MS = 1000;

  /** True instants the receiver decoded a position, on the irregular 2-10 s
   * cadence of a distant aircraft. */
  const FIX_TIMES_MS = [500, 4300, 9100];

  const POLL_TIMES_MS = [
    1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000, 10_000, 11_000,
    12_000,
  ];

  /** Where the aircraft truly is `trueMs` after T0. */
  function latAtTrue(trueMs: number): number {
    return (trueMs / 1000) * DEGREES_PER_SECOND;
  }

  /** The newest fix the decoder held when the backend polled at `pollMs`. */
  function fixHeldAt(pollMs: number): number {
    let held = FIX_TIMES_MS[0] as number;
    for (const measuredAt of FIX_TIMES_MS) {
      if (measuredAt <= pollMs) {
        held = measuredAt;
      }
    }
    return held;
  }

  /** Applies the frame built by the poll at `pollMs`, at the browser instant it
   * would land. Returns that instant. */
  function deliverPoll(pollMs: number): number {
    const measuredAt = fixHeldAt(pollMs);
    const arrivesAt = T0 + pollMs + TRANSPORT_MS;
    useLiveAircraftStore.getState().applyDelta(
      {
        updated: [
          inbound({
            position: { lat: latAtTrue(measuredAt), lon: 0 },
            seen_pos_s: (pollMs - measuredAt) / 1000,
          }),
        ],
        stale: [],
        removed: [],
      },
      arrivesAt,
    );
    return arrivesAt;
  }

  function rawLat(): number {
    const lat =
      useLiveAircraftStore.getState().aircraft[ICAO]?.aircraft.position?.lat;
    if (lat === undefined) {
      throw new Error(`${ICAO} has no reported position`);
    }
    return lat;
  }

  beforeEach(() => {
    // The suite-wide snapshot seeds an unaged fix; this scenario builds its own
    // history from the first poll.
    useLiveAircraftStore.getState().reset();
  });

  it("never draws the aircraft behind where it was a moment earlier", () => {
    // The reported symptom: a periodic back-step, once per genuine decode. The
    // last sample of each second sits 1 ms before the next frame lands, so a
    // step at the handover has nowhere to hide between samples.
    let previous = Number.NEGATIVE_INFINITY;
    for (const pollMs of POLL_TIMES_MS) {
      const arrivesAt = deliverPoll(pollMs);
      for (const offset of [0, 250, 500, 750, 999]) {
        const current = drawnLat(arrivesAt + offset);
        expect(
          current,
          `drew backwards at poll ${pollMs} ms +${offset}: ${current} < ${previous}`,
        ).toBeGreaterThanOrEqual(previous);
        previous = current;
      }
    }
  });

  it("hands over from one fix to the next without a step", () => {
    // The fix measured at 4300 first reaches the browser at T0+6000, carried by
    // the 5000 poll and 0.7 s old. Either side of that instant the drawn path
    // must differ by one millisecond of travel and nothing more.
    for (const pollMs of [1000, 2000, 3000, 4000]) {
      deliverPoll(pollMs);
    }
    const before = drawnLat(T0 + 5999);

    deliverPoll(5000);

    expect(drawnLat(T0 + 6000) - before).toBeCloseTo(
      DEGREES_PER_SECOND / 1000,
      12,
    );
  });

  it("draws a new fix ahead of its raw coordinates, never back at them", () => {
    // Why the old dating had to rewind: the coordinates a frame reports were
    // measured before the poll that carried them, so they are already behind
    // the projection running from the previous fix. Drawing them where they
    // are read is the back-step; drawing them plus their own age is not.
    for (const pollMs of [1000, 2000, 3000, 4000]) {
      deliverPoll(pollMs);
    }
    const before = drawnLat(T0 + 5999);

    deliverPoll(5000);

    expect(rawLat()).toBeLessThan(before);
    expect(drawnLat(T0 + 6000)).toBeGreaterThan(rawLat());
    expect(drawnLat(T0 + 6000)).toBeGreaterThanOrEqual(before);
  });

  it("tracks the true position, lagged only by the transport it cannot see", () => {
    // The strongest statement of the fix: at the moment each frame lands, the
    // marker sits exactly where the aircraft was when the backend polled —
    // every fix, whatever its decode age. Only the shared transport lag is
    // left, and no arithmetic on this data could remove it.
    for (const pollMs of POLL_TIMES_MS) {
      const arrivesAt = deliverPoll(pollMs);
      expect(drawnLat(arrivesAt)).toBeCloseTo(latAtTrue(pollMs), 9);
    }
  });

  it("still freezes rather than rewinding when the stream dies mid-flight", () => {
    // Slice 054's stall grace is untouched: it is measured from `receivedAt`,
    // which back-dating does not move.
    const arrivesAt = deliverPoll(1000);
    const coasted = drawnLat(arrivesAt + 60_000);

    expect(coasted).toBeGreaterThan(drawnLat(arrivesAt));
    expect(drawnLat(arrivesAt + 600_000)).toBe(coasted);
  });
});
