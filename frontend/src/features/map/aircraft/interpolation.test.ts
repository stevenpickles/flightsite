import { describe, expect, it } from "vitest";

import {
  displayPosition,
  INTERPOLATION_MAX_FIX_AGE_MS,
  INTERPOLATION_STALL_GRACE_MS,
  normalizeLongitude,
  projectPosition,
} from "@/features/map/aircraft/interpolation";
import type { LiveAircraftRecord } from "@/features/map/aircraft/store/useLiveAircraftStore";
import type { LiveAircraft } from "@/lib/api/live";
import type { RecordTimes } from "@/test/liveAircraftFixtures";
import { makeRecord } from "@/test/liveAircraftFixtures";

const ONE_HOUR = 3_600_000;

/** A record whose stream is healthy at `now`: `receivedAt` tracks the caller's
 * clock, so these cases exercise the fix-age bound rather than the stall
 * grace. Tests that care about a stalled stream set `receivedAt` explicitly. */
function record(
  overrides: Partial<LiveAircraft>,
  times: RecordTimes = {},
): LiveAircraftRecord {
  return makeRecord(overrides, times);
}

/** A record still receiving frames at `now`, with a fix `fixAgeMs` old. */
function streaming(
  overrides: Partial<LiveAircraft>,
  now: number,
  fixAgeMs: number,
): LiveAircraftRecord {
  return makeRecord(overrides, {
    receivedAt: now,
    positionChangedAt: now - fixAgeMs,
  });
}

describe("projectPosition", () => {
  it("moves due north at 60 kt for one hour: one degree of latitude", () => {
    const result = projectPosition({ lat: 0, lon: 0 }, 0, 60, ONE_HOUR);
    expect(result.lat).toBeCloseTo(1, 9);
    expect(result.lon).toBeCloseTo(0, 9);
  });

  it("moves due south on a 180 degree track", () => {
    const result = projectPosition({ lat: 10, lon: 5 }, 180, 60, ONE_HOUR);
    expect(result.lat).toBeCloseTo(9, 9);
    expect(result.lon).toBeCloseTo(5, 9);
  });

  it("moves due east on a 090 track, scaled by the cosine of latitude", () => {
    const result = projectPosition({ lat: 60, lon: 0 }, 90, 60, ONE_HOUR);
    // At 60°N a degree of longitude is half a degree of latitude on the ground.
    expect(result.lon).toBeCloseTo(2, 6);
    expect(result.lat).toBeCloseTo(60, 9);
  });

  it("splits a 045 track evenly between north and east at the equator", () => {
    const result = projectPosition({ lat: 0, lon: 0 }, 45, 60, ONE_HOUR);
    expect(result.lat).toBeCloseTo(Math.SQRT1_2, 9);
    expect(result.lon).toBeCloseTo(Math.SQRT1_2, 9);
  });

  it("wraps across the antimeridian", () => {
    const result = projectPosition({ lat: 0, lon: 179.99 }, 90, 60, ONE_HOUR);
    expect(result.lon).toBeCloseTo(-179.01, 6);
  });

  it("stays finite at the pole", () => {
    const result = projectPosition({ lat: 89.99, lon: 0 }, 90, 600, ONE_HOUR);
    expect(Number.isFinite(result.lon)).toBe(true);
    expect(result.lat).toBeLessThanOrEqual(90);
  });

  it("clamps latitude to the poles", () => {
    const result = projectPosition({ lat: 89.9, lon: 0 }, 0, 600, ONE_HOUR);
    expect(result.lat).toBe(90);
  });
});

describe("normalizeLongitude", () => {
  it.each([
    [0, 0],
    [180, -180],
    [-180, -180],
    [181, -179],
    [-181, 179],
    [540, -180],
  ])("maps %s to %s", (input, expected) => {
    expect(normalizeLongitude(input)).toBeCloseTo(expected, 9);
  });
});

describe("displayPosition", () => {
  it("dead-reckons an airborne aircraft forward from its last report", () => {
    const result = displayPosition(
      record({
        position: { lat: 0, lon: 0 },
        track_deg: 0,
        ground_speed_kt: 360,
      }),
      1000,
    );
    // 360 kt for one second is 0.1 nm, or 1/600 of a degree.
    expect(result?.lat).toBeCloseTo(0.1 / 60, 9);
  });

  it("never projects a stale aircraft", () => {
    // Staleness means the receiver has stopped hearing it; extrapolating its
    // last velocity would be fabricating a position.
    const result = displayPosition(
      record({
        state: "stale",
        position: { lat: 5, lon: 6 },
        track_deg: 90,
        ground_speed_kt: 400,
      }),
      5000,
    );
    expect(result).toEqual({ lat: 5, lon: 6 });
  });

  it("never projects an aircraft on the ground", () => {
    const result = displayPosition(
      record({
        on_ground: true,
        position: { lat: 5, lon: 6 },
        track_deg: 90,
        ground_speed_kt: 15,
      }),
      5000,
    );
    expect(result).toEqual({ lat: 5, lon: 6 });
  });

  it("stops projecting once the stream has stalled", () => {
    // No frame since t=0: the projection may coast for the grace period and
    // must then hold, however long the stall lasts.
    const moving = {
      position: { lat: 0, lon: 0 },
      track_deg: 0,
      ground_speed_kt: 60,
    };
    const capped = displayPosition(
      record(moving),
      INTERPOLATION_STALL_GRACE_MS,
    );
    expect(
      displayPosition(record(moving), INTERPOLATION_STALL_GRACE_MS * 10),
    ).toEqual(capped);
    expect(displayPosition(record(moving), ONE_HOUR)).toEqual(capped);
  });

  it("freezes at the projection it reached, not back at the raw fix", () => {
    // The stall must look like the aircraft stopping, never like it jumping
    // backwards — a rewind is the defect this module exists to avoid.
    const frozen = displayPosition(
      record({
        position: { lat: 0, lon: 0 },
        track_deg: 0,
        ground_speed_kt: 600,
      }),
      ONE_HOUR,
    );
    expect(frozen?.lat).toBeGreaterThan(0);
    // 600 kt for the 4 s grace is 0.667 nm.
    expect(frozen?.lat).toBeCloseTo(
      (600 * INTERPOLATION_STALL_GRACE_MS) / ONE_HOUR / 60,
      9,
    );
  });

  it("keeps projecting a live aircraft whose fix is older than the grace", () => {
    // The regression guard for the bound itself: a distant aircraft heard
    // every second but positioned every 8 s must not freeze at 4 s.
    const now = 100_000;
    const drawn = displayPosition(
      streaming(
        { position: { lat: 0, lon: 0 }, track_deg: 0, ground_speed_kt: 360 },
        now,
        8_000,
      ),
      now,
    );
    // 360 kt for eight seconds is 0.8 nm.
    expect(drawn?.lat).toBeCloseTo(0.8 / 60, 9);
  });

  it("stops dead-reckoning a fix older than the fix-age cap", () => {
    // Heard every second, positioned never: a Mode S-only aircraft stays live
    // but must not be flown across the map on an unconfirmed velocity.
    const now = 100_000;
    const moving = {
      position: { lat: 0, lon: 0 },
      track_deg: 0,
      ground_speed_kt: 360,
    };
    const atCap = displayPosition(
      streaming(moving, now, INTERPOLATION_MAX_FIX_AGE_MS),
      now,
    );
    expect(
      displayPosition(
        streaming(moving, now, INTERPOLATION_MAX_FIX_AGE_MS * 20),
        now,
      ),
    ).toEqual(atCap);
  });

  it("covers the distant-aircraft fix cadence with the fix-age cap", () => {
    // The bound is only correct if it clears the 2-10 s CPR cadence that
    // motivated it, with room to spare.
    expect(INTERPOLATION_MAX_FIX_AGE_MS).toBeGreaterThan(10_000);
  });

  it("returns the reported position when velocity is unknown", () => {
    expect(
      displayPosition(
        record({ position: { lat: 1, lon: 2 }, track_deg: null }),
        3000,
      ),
    ).toEqual({ lat: 1, lon: 2 });
    expect(
      displayPosition(
        record({ position: { lat: 1, lon: 2 }, ground_speed_kt: null }),
        3000,
      ),
    ).toEqual({ lat: 1, lon: 2 });
    expect(
      displayPosition(
        record({ position: { lat: 1, lon: 2 }, ground_speed_kt: 0 }),
        3000,
      ),
    ).toEqual({ lat: 1, lon: 2 });
  });

  it("does not project backwards when the clock runs behind the record", () => {
    expect(
      displayPosition(
        record(
          { position: { lat: 1, lon: 2 }, track_deg: 0, ground_speed_kt: 400 },
          { receivedAt: 5000 },
        ),
        1000,
      ),
    ).toEqual({ lat: 1, lon: 2 });
  });

  it("returns null for a non-positioned aircraft", () => {
    // Mode S only: tracked (SPEC §20), but not something the map can place.
    expect(
      displayPosition(record({ position: null, position_source: "none" }), 0),
    ).toBeNull();
  });
});
