import { beforeEach, describe, expect, it } from "vitest";

import type { LiveAircraftRecord } from "@/features/map/aircraft/store/useLiveAircraftStore";
import {
  liveTrails,
  resetTrails,
  TRAIL_MAX_AGE_MS,
  TRAIL_MAX_POINTS,
  TrailBuffer,
} from "@/features/map/aircraft/trails";
import type { LiveAircraft } from "@/lib/api/live";
import { makeRecord } from "@/test/liveAircraftFixtures";

const T0 = 1_800_000_000_000;

/** One aircraft's record, fixed at `at` (browser clock) at `lat`. */
function fix(
  icao: string,
  at: number,
  lat: number,
  overrides: Partial<LiveAircraft> = {},
): LiveAircraftRecord {
  return makeRecord(
    { icao, position: { lat, lon: -122 }, ...overrides },
    { receivedAt: at, positionChangedAt: at },
  );
}

function picture(
  ...records: LiveAircraftRecord[]
): Record<string, LiveAircraftRecord> {
  return Object.fromEntries(
    records.map((record) => [record.aircraft.icao, record]),
  );
}

let buffer: TrailBuffer;

beforeEach(() => {
  buffer = new TrailBuffer();
});

describe("TrailBuffer", () => {
  it("records one point per fix, oldest first", () => {
    buffer.record(picture(fix("aaaaaa", T0, 47.0)), T0);
    buffer.record(picture(fix("aaaaaa", T0 + 1000, 47.1)), T0 + 1000);
    buffer.record(picture(fix("aaaaaa", T0 + 2000, 47.2)), T0 + 2000);

    expect(buffer.coordinates("aaaaaa", T0 + 2000)).toEqual([
      [-122, 47.0],
      [-122, 47.1],
      [-122, 47.2],
    ]);
  });

  it("records a repeated fix once, however often it is fed", () => {
    // The frame loop feeds the buffer on every picture/filter/toggle redraw;
    // a fix the store carries forward unchanged keeps its positionChangedAt.
    const record = fix("aaaaaa", T0, 47.0);
    for (let tick = 0; tick < 10; tick += 1) {
      buffer.record(picture(record), T0 + tick * 100);
    }
    expect(buffer.pointCount("aaaaaa")).toBe(1);
  });

  it("never appends a fix older than the trail's newest point", () => {
    buffer.record(picture(fix("aaaaaa", T0 + 1000, 47.1)), T0 + 1000);
    buffer.record(picture(fix("aaaaaa", T0, 47.0)), T0 + 1000);
    expect(buffer.coordinates("aaaaaa", T0 + 1000)).toEqual([[-122, 47.1]]);
  });

  it(`caps a trail at ${TRAIL_MAX_POINTS} points, keeping the newest`, () => {
    const fixes = TRAIL_MAX_POINTS + 12;
    for (let index = 0; index < fixes; index += 1) {
      const at = T0 + index * 1000;
      buffer.record(picture(fix("aaaaaa", at, 40 + index / 100)), at);
    }
    const now = T0 + (fixes - 1) * 1000;
    const coordinates = buffer.coordinates("aaaaaa", now);

    expect(buffer.pointCount("aaaaaa")).toBe(TRAIL_MAX_POINTS);
    expect(coordinates).toHaveLength(TRAIL_MAX_POINTS);
    // The oldest twelve are gone; the newest is last.
    expect(coordinates[0]).toEqual([-122, 40 + 12 / 100]);
    expect(coordinates.at(-1)).toEqual([-122, 40 + (fixes - 1) / 100]);
  });

  it("caps a trail by age, even below the point cap", () => {
    // An MLAT-rate contact: a fix every 30 s would reach the point cap only
    // after 15 minutes; the age cap keeps its trail to the last 2 minutes.
    const interval = 30_000;
    for (let index = 0; index <= 10; index += 1) {
      const at = T0 + index * interval;
      buffer.record(picture(fix("aaaaaa", at, 40 + index)), at);
    }
    const now = T0 + 10 * interval;
    const coordinates = buffer.coordinates("aaaaaa", now);

    expect(coordinates.length).toBeLessThan(TRAIL_MAX_POINTS);
    expect(coordinates).toHaveLength(TRAIL_MAX_AGE_MS / interval + 1);
    expect(coordinates[0]).toEqual([
      -122,
      40 + 10 - TRAIL_MAX_AGE_MS / interval,
    ]);
    expect(buffer.pointCount("aaaaaa")).toBe(coordinates.length);
  });

  it("drains a stale aircraft's trail as its points age out", () => {
    const stale = fix("aaaaaa", T0, 47.0, { state: "stale" });
    buffer.record(picture(fix("aaaaaa", T0 - 1000, 46.9)), T0 - 1000);
    buffer.record(picture(stale), T0);
    expect(buffer.pointCount("aaaaaa")).toBe(2);

    // Still in the store, no new fix, and now past the age cap.
    buffer.record(picture(stale), T0 + TRAIL_MAX_AGE_MS + 1);
    expect(buffer.pointCount("aaaaaa")).toBe(0);
    expect(buffer.size).toBe(0);
    expect(buffer.coordinates("aaaaaa", T0 + TRAIL_MAX_AGE_MS + 1)).toEqual([]);
  });

  it("hides points past the age cap at read time, before the next record", () => {
    buffer.record(picture(fix("aaaaaa", T0, 47.0)), T0);
    buffer.record(picture(fix("aaaaaa", T0 + 1000, 47.1)), T0 + 1000);
    expect(buffer.coordinates("aaaaaa", T0 + TRAIL_MAX_AGE_MS + 500)).toEqual([
      [-122, 47.1],
    ]);
  });

  it("forgets an aircraft the moment it leaves the live store", () => {
    buffer.record(
      picture(fix("aaaaaa", T0, 47.0), fix("bbbbbb", T0, 48.0)),
      T0,
    );
    expect(buffer.size).toBe(2);

    buffer.record(picture(fix("bbbbbb", T0 + 1000, 48.1)), T0 + 1000);
    expect(buffer.size).toBe(1);
    expect(buffer.pointCount("aaaaaa")).toBe(0);
    expect(buffer.coordinates("aaaaaa", T0 + 1000)).toEqual([]);
  });

  it("stays bounded by the live picture as aircraft churn through it", () => {
    // 2,000 distinct aircraft pass through a picture that never holds more
    // than 50 at once: the buffer tracks the picture, not the history.
    let peak = 0;
    for (let tick = 0; tick < 200; tick += 1) {
      const at = T0 + tick * 1000;
      const records = Array.from({ length: 50 }, (_, index) =>
        fix((tick * 10 + index).toString(16).padStart(6, "0"), at, 40 + index),
      );
      buffer.record(picture(...records), at);
      peak = Math.max(peak, buffer.size);
    }
    expect(peak).toBeLessThanOrEqual(50);
  });

  it("skips aircraft with no position", () => {
    buffer.record(picture(fix("aaaaaa", T0, 0, { position: null })), T0);
    expect(buffer.size).toBe(0);
  });

  it("clear() drops every trail", () => {
    buffer.record(picture(fix("aaaaaa", T0, 47.0)), T0);
    buffer.clear();
    expect(buffer.size).toBe(0);
  });
});

describe("liveTrails / resetTrails", () => {
  it("resetTrails empties the shared buffer", () => {
    liveTrails.record(picture(fix("aaaaaa", T0, 47.0)), T0);
    expect(liveTrails.size).toBe(1);
    resetTrails();
    expect(liveTrails.size).toBe(0);
  });
});
