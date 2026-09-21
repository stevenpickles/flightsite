import { describe, expect, it } from "vitest";

import { describePathSample } from "@/features/sighting-detail/lib/pathSample";

describe("describePathSample", () => {
  it("names the reduction for a closed sighting", () => {
    // The review's case: 11 drawn vertices beside "Position reports 543".
    expect(describePathSample(11, 543, false)).toBe(
      "11 points, simplified from 543 position reports.",
    );
  });

  it("names the cadence and where the full track is for an open one", () => {
    const text = describePathSample(20, 943, true) ?? "";
    expect(text).toContain("20 points");
    expect(text).toContain("30 seconds");
    expect(text).toContain("Live Map");
  });

  it("says nothing when there is no path drawn", () => {
    // The map is showing "no path was recorded for this sighting", which
    // says more than a count of zero would.
    expect(describePathSample(0, 0, false)).toBeNull();
  });

  it("uses singulars where singulars are right", () => {
    expect(describePathSample(1, 1, false)).toBe(
      "1 point, simplified from 1 position report.",
    );
  });

  it("groups large counts the way the rest of the page does", () => {
    expect(describePathSample(18, 12_405, false)).toBe(
      "18 points, simplified from 12,405 position reports.",
    );
  });
});
