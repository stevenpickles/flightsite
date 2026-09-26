import { describe, expect, it } from "vitest";

import {
  buildAvailabilitySegments,
  computeAvailability,
  computeAvailabilityPct,
  windowDurationMs,
} from "@/features/feeders/lib/availability";

const NOW = new Date("2026-09-26T12:00:00.000Z");

describe("windowDurationMs", () => {
  it("maps each window to its millisecond span", () => {
    expect(windowDurationMs("24h")).toBe(24 * 60 * 60 * 1000);
    expect(windowDurationMs("7d")).toBe(7 * 24 * 60 * 60 * 1000);
    expect(windowDurationMs("30d")).toBe(30 * 24 * 60 * 60 * 1000);
  });
});

describe("buildAvailabilitySegments", () => {
  it("renders the whole window as unknown when there are no episodes", () => {
    const segments = buildAvailabilitySegments([], "24h", NOW);

    expect(segments).toHaveLength(1);
    expect(segments[0]).toMatchObject({
      state: "unknown",
      startPct: 0,
      widthPct: 100,
    });
  });

  it("renders one full-width segment for an episode spanning the whole window", () => {
    const segments = buildAvailabilitySegments(
      [
        {
          state: "up",
          started_at: "2026-09-24T00:00:00.000Z",
          ended_at: null,
        },
      ],
      "24h",
      NOW,
    );

    expect(segments).toHaveLength(1);
    expect(segments[0]?.state).toBe("up");
    expect(segments[0]?.startPct).toBeCloseTo(0, 5);
    expect(segments[0]?.widthPct).toBeCloseTo(100, 5);
  });

  it("fills the gap before the first episode and after the last with unknown", () => {
    // Window is [12:00 yesterday, 12:00 today]. One down episode in the
    // middle third, nothing recorded before or after it.
    const segments = buildAvailabilitySegments(
      [
        {
          state: "down",
          started_at: "2026-09-26T00:00:00.000Z",
          ended_at: "2026-09-26T06:00:00.000Z",
        },
      ],
      "24h",
      NOW,
    );

    expect(segments.map((segment) => segment.state)).toEqual([
      "unknown",
      "down",
      "unknown",
    ]);
    // unknown [12:00 -> 00:00] = 12h = 50%, down [00:00 -> 06:00] = 6h = 25%,
    // unknown [06:00 -> 12:00] = 6h = 25%.
    expect(segments[0]?.widthPct).toBeCloseTo(50, 5);
    expect(segments[1]?.widthPct).toBeCloseTo(25, 5);
    expect(segments[2]?.widthPct).toBeCloseTo(25, 5);
    // Contiguous: each segment starts exactly where the previous ended.
    expect(segments[1]?.startPct).toBeCloseTo(
      (segments[0]?.startPct ?? 0) + (segments[0]?.widthPct ?? 0),
      5,
    );
  });

  it("clips an episode that starts before the window to the window's start", () => {
    const segments = buildAvailabilitySegments(
      [
        {
          state: "up",
          started_at: "2020-01-01T00:00:00.000Z",
          ended_at: "2026-09-26T06:00:00.000Z",
        },
      ],
      "24h",
      NOW,
    );

    expect(segments).toHaveLength(2);
    expect(segments[0]).toMatchObject({ state: "up", startPct: 0 });
    expect(segments[0]?.widthPct).toBeCloseTo(75, 5);
    expect(segments[1]?.state).toBe("unknown");
  });

  it("clips an ongoing (ended_at: null) episode to now", () => {
    const segments = buildAvailabilitySegments(
      [
        {
          state: "degraded",
          started_at: "2026-09-26T06:00:00.000Z",
          ended_at: null,
        },
      ],
      "24h",
      NOW,
    );

    const last = segments.at(-1);
    expect(last?.state).toBe("degraded");
    expect((last?.startPct ?? 0) + (last?.widthPct ?? 0)).toBeCloseTo(100, 5);
  });

  it("drops an episode that ended entirely before the window", () => {
    const segments = buildAvailabilitySegments(
      [
        {
          state: "down",
          started_at: "2020-01-01T00:00:00.000Z",
          ended_at: "2020-01-02T00:00:00.000Z",
        },
      ],
      "24h",
      NOW,
    );

    expect(segments).toHaveLength(1);
    expect(segments[0]?.state).toBe("unknown");
  });
});

describe("computeAvailabilityPct", () => {
  it("is 100 when every segment is up", () => {
    const segments = buildAvailabilitySegments(
      [{ state: "up", started_at: "2026-09-25T12:00:00.000Z", ended_at: null }],
      "24h",
      NOW,
    );
    expect(computeAvailabilityPct(segments)).toBeCloseTo(100, 5);
  });

  it("is 0 when nothing was ever up", () => {
    const segments = buildAvailabilitySegments(
      [
        {
          state: "down",
          started_at: "2026-09-25T12:00:00.000Z",
          ended_at: null,
        },
      ],
      "24h",
      NOW,
    );
    expect(computeAvailabilityPct(segments)).toBe(0);
  });

  it("scores only the observed span, and says how long that was", () => {
    // Up for the last six hours of a 24-hour window, unobserved before that:
    // 100 % of six hours, not 25 % of a day.
    const segments = buildAvailabilitySegments(
      [
        {
          state: "up",
          started_at: "2026-09-26T06:00:00.000Z",
          ended_at: null,
        },
      ],
      "24h",
      NOW,
    );
    const availability = computeAvailability(segments, "24h");
    expect(availability.pct).toBeCloseTo(100, 5);
    expect(availability.observedMs).toBe(6 * 60 * 60 * 1000);
    expect(availability.windowMs).toBe(24 * 60 * 60 * 1000);
    expect(computeAvailabilityPct(segments, "24h")).toBeCloseTo(100, 5);
  });

  it("divides up-time by the observed span when part of it was down", () => {
    // Observed for the last six hours: down for the first three, up since.
    const segments = buildAvailabilitySegments(
      [
        {
          state: "down",
          started_at: "2026-09-26T06:00:00.000Z",
          ended_at: "2026-09-26T09:00:00.000Z",
        },
        {
          state: "up",
          started_at: "2026-09-26T09:00:00.000Z",
          ended_at: null,
        },
      ],
      "24h",
      NOW,
    );
    expect(computeAvailability(segments, "24h").pct).toBeCloseTo(50, 5);
  });

  it("is null, not zero, when nothing in the window was observed", () => {
    const segments = buildAvailabilitySegments([], "24h", NOW);
    expect(computeAvailability(segments, "24h").pct).toBeNull();
    expect(computeAvailabilityPct(segments, "24h")).toBeNull();
  });
});
