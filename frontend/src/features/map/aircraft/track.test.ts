import { describe, expect, it } from "vitest";

import type { TrackPoint } from "@/features/map/aircraft/track";
import {
  appendTrackPoint,
  mergeTrackPoints,
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

describe("mergeTrackPoints", () => {
  const at = (points: readonly TrackPoint[]) => points.map((entry) => entry.at);

  it("prepends history to points accumulated since selection", () => {
    // The issue #133 case: the click happened at t=10, so everything the
    // client watched starts there and the sighting's earlier path is fetched.
    const merged = mergeTrackPoints(
      [point(47.0, -122, 1), point(47.1, -122, 5)],
      [point(47.3, -122, 10), point(47.4, -122, 11)],
    );
    expect(at(merged)).toEqual([1, 5, 10, 11]);
  });

  it("returns the fetched history alone when nothing has accumulated yet", () => {
    const merged = mergeTrackPoints([point(47, -122, 1)], []);
    expect(at(merged)).toEqual([1]);
  });

  it("returns the accumulated points unchanged when there is no history", () => {
    // Identity, not a copy: an empty backfill must not churn `setData`.
    const points = [point(47, -122, 1)];
    expect(mergeTrackPoints([], points)).toBe(points);
  });

  it("returns the accumulated points unchanged when history adds nothing", () => {
    const points = [point(47, -122, 1), point(47.1, -122, 2)];
    expect(mergeTrackPoints([point(47, -122, 1)], points)).toBe(points);
  });

  it("collapses the overlap the checkpoint lag produces", () => {
    // The checkpointed path runs past the moment of selection, so its tail and
    // the live-accumulated head describe the same stretch of flight.
    const merged = mergeTrackPoints(
      [point(47.0, -122, 1), point(47.1, -122, 5), point(47.2, -122, 9)],
      [point(47.25, -122, 9), point(47.3, -122, 12)],
    );
    expect(at(merged)).toEqual([1, 5, 9, 12]);
  });

  it("keeps the live point on a timestamp collision", () => {
    // The client watched that fix arrive; the checkpoint is a summary of it.
    const merged = mergeTrackPoints(
      [point(47.2, -122, 9)],
      [point(47.25, -122, 9)],
    );
    expect(merged).toEqual([{ lat: 47.25, lon: -122, at: 9 }]);
  });

  it("interleaves points that alternate between the two lists", () => {
    const merged = mergeTrackPoints(
      [point(47.0, -122, 1), point(47.2, -122, 3)],
      [point(47.1, -122, 2), point(47.3, -122, 4)],
    );
    expect(at(merged)).toEqual([1, 2, 3, 4]);
  });

  it("drops a history point that does not advance the clock", () => {
    // Neither list is trusted to be perfectly sorted: a merge that honoured an
    // out-of-order point would draw a polyline that doubles back on itself.
    const merged = mergeTrackPoints(
      [point(47.0, -122, 1), point(47.2, -122, 7), point(47.1, -122, 4)],
      [point(47.3, -122, 10)],
    );
    expect(at(merged)).toEqual([1, 7, 10]);
  });

  it("drops an accumulated point that does not advance the clock", () => {
    const merged = mergeTrackPoints(
      [point(47.0, -122, 1)],
      [point(47.3, -122, 10), point(47.2, -122, 6)],
    );
    expect(at(merged)).toEqual([1, 10]);
  });

  it("caps the merged track, keeping the newest points", () => {
    const history = Array.from({ length: TRACK_MAX_POINTS }, (_unused, i) =>
      point(47 + i / 10000, -122, i + 1),
    );
    const live = Array.from({ length: 50 }, (_unused, i) =>
      point(48 + i / 10000, -122, TRACK_MAX_POINTS + i + 1),
    );

    const merged = mergeTrackPoints(history, live);

    expect(merged).toHaveLength(TRACK_MAX_POINTS);
    expect(merged[0]?.at).toBe(51);
    expect(merged.at(-1)?.at).toBe(TRACK_MAX_POINTS + 50);
  });

  it("returns an empty track when both lists are empty", () => {
    expect(mergeTrackPoints([], [])).toEqual([]);
  });
});
