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

  it("never interleaves history into the region the live list covers", () => {
    // The live list is authoritative from its first point onwards; a history
    // point landing inside that window is a clock artefact, not a fix the
    // aircraft reported between two watched ones.
    const merged = mergeTrackPoints(
      [point(47.0, -122, 1), point(47.2, -122, 3)],
      [point(47.1, -122, 2), point(47.3, -122, 4)],
    );
    expect(at(merged)).toEqual([1, 2, 4]);
  });

  it("backfills nothing when the receiver clock runs ahead of the browser", () => {
    // The fold: the receiver's clock is 5 minutes ahead, and the aircraft was
    // airborne for only 2 minutes before the click, so every history point is
    // stamped *after* the live ones. Merged naively the polyline would draw
    // the current position, jump back to where the aircraft was two minutes
    // ago, and re-trace forward. Clamping degrades to the pre-backfill
    // picture instead of drawing a line no aircraft flew.
    const skew = 300_000;
    const selectedAt = 1_800_000_000_000;
    const history = [
      point(47.0, -122, selectedAt - 120_000 + skew),
      point(47.2, -122, selectedAt - 60_000 + skew),
      point(47.4, -122, selectedAt + skew),
    ];
    const live = [
      point(47.5, -122, selectedAt),
      point(47.51, -122, selectedAt + 1000),
    ];

    expect(mergeTrackPoints(history, live)).toBe(live);
  });

  it("keeps the history a modest skew leaves genuinely older", () => {
    // The same skew against a sighting that has been open long enough to
    // outrun it: the part of the history still older than the first live point
    // is real and is drawn.
    const skew = 60_000;
    const selectedAt = 1_800_000_000_000;
    const history = [
      point(47.0, -122, selectedAt - 600_000 + skew),
      point(47.2, -122, selectedAt - 300_000 + skew),
      point(47.4, -122, selectedAt + skew),
    ];
    const live = [point(47.5, -122, selectedAt)];

    expect(at(mergeTrackPoints(history, live))).toEqual([
      selectedAt - 540_000,
      selectedAt - 240_000,
      selectedAt,
    ]);
  });

  it("sorts an out-of-order history point into place", () => {
    // Neither list is trusted to be perfectly sorted: honouring the given
    // order would draw a polyline that doubles back on itself.
    const merged = mergeTrackPoints(
      [point(47.0, -122, 1), point(47.2, -122, 7), point(47.1, -122, 4)],
      [point(47.3, -122, 10)],
    );
    expect(at(merged)).toEqual([1, 4, 7, 10]);
  });

  it("sorts an out-of-order accumulated point into place", () => {
    const merged = mergeTrackPoints(
      [point(47.0, -122, 1)],
      [point(47.3, -122, 10), point(47.2, -122, 6)],
    );
    expect(at(merged)).toEqual([1, 6, 10]);
  });

  it("loses no later points to a single out-of-order history point", () => {
    // Issue #137: the strictly-increasing rule was an amplifier, not a reorder
    // guard — one spike at t=100 discarded every point after it, turning one
    // bad point into four lost ones.
    const merged = mergeTrackPoints(
      [
        point(47.0, -122, 1),
        point(48.0, -122, 100),
        point(47.1, -122, 2),
        point(47.2, -122, 3),
        point(47.3, -122, 4),
        point(47.4, -122, 5),
      ],
      [],
    );
    expect(at(merged)).toEqual([1, 2, 3, 4, 5, 100]);
  });

  it("keeps the out-of-order point itself, in its sorted position", () => {
    const merged = mergeTrackPoints(
      [point(47.0, -122, 1), point(47.9, -122, 9), point(47.1, -122, 3)],
      [point(48.0, -122, 20)],
    );
    expect(merged).toEqual([
      { lat: 47.0, lon: -122, at: 1 },
      { lat: 47.1, lon: -122, at: 3 },
      { lat: 47.9, lon: -122, at: 9 },
      { lat: 48.0, lon: -122, at: 20 },
    ]);
  });

  it("de-duplicates repeated timestamps inside one list", () => {
    const merged = mergeTrackPoints(
      [point(47.0, -122, 1), point(47.05, -122, 1)],
      [point(47.3, -122, 10)],
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
