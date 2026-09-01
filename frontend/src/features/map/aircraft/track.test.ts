import { describe, expect, it } from "vitest";

import type { TrackPoint } from "@/features/map/aircraft/track";
import {
  appendTrackPoint,
  TRACK_MAX_POINTS,
} from "@/features/map/aircraft/track";

const point = (lat: number, lon: number, at = 0): TrackPoint => ({
  lat,
  lon,
  at,
});

describe("appendTrackPoint", () => {
  it("appends to an empty track", () => {
    expect(appendTrackPoint([], point(47, -122, 5))).toEqual([
      { lat: 47, lon: -122, at: 5 },
    ]);
  });

  it("keeps points in arrival order", () => {
    const points = appendTrackPoint(
      appendTrackPoint([], point(47, -122, 1)),
      point(48, -122, 2),
    );
    expect(points.map((entry) => entry.at)).toEqual([1, 2]);
  });

  it("returns the same array when the position repeats", () => {
    // An aircraft on a stand repeats its position indefinitely; those repeats
    // must not consume the retention window or trigger a redraw.
    const points = appendTrackPoint([], point(47, -122, 1));
    expect(appendTrackPoint(points, point(47, -122, 2))).toBe(points);
  });

  it("keeps a point that changes only in longitude", () => {
    const points = appendTrackPoint([], point(47, -122, 1));
    expect(appendTrackPoint(points, point(47, -122.1, 2))).toHaveLength(2);
  });

  it("drops the oldest points past the cap", () => {
    let points: TrackPoint[] = [];
    for (let i = 0; i < TRACK_MAX_POINTS + 10; i += 1) {
      points = appendTrackPoint(points, point(47 + i / 10000, -122, i));
    }
    expect(points).toHaveLength(TRACK_MAX_POINTS);
    expect(points[0]?.at).toBe(10);
    expect(points.at(-1)?.at).toBe(TRACK_MAX_POINTS + 9);
  });
});
