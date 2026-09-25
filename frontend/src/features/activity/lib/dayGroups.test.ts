import { describe, expect, it } from "vitest";

import { groupActivityByDay } from "@/features/activity/lib/dayGroups";
import { activityEvent } from "@/test/activityApiMock";

/** 2026-09-21T01:43Z is 2026-09-20 21:43 in New York — the case the review
 * ran the whole audit against (browser `Europe/London`, receiver
 * `America/New_York`). */
const NOW = new Date("2026-09-21T01:50:00.000Z");

function at(iso: string, id: number) {
  return activityEvent({ id, at: iso });
}

describe("groupActivityByDay", () => {
  it("groups by the receiver's day, not the UTC one", () => {
    const groups = groupActivityByDay(
      [at("2026-09-21T01:43:00.000Z", 1)],
      "America/New_York",
      NOW,
    );

    expect(groups).toHaveLength(1);
    expect(groups[0]?.key).toBe("2026-09-20");
  });

  it("names today and yesterday, and dates anything older", () => {
    const groups = groupActivityByDay(
      [
        at("2026-09-21T01:43:00.000Z", 1), // 2026-09-20 local — "today"
        at("2026-09-20T12:00:00.000Z", 2), // 2026-09-20 local — same day
        at("2026-09-20T01:00:00.000Z", 3), // 2026-09-19 local — "yesterday"
        at("2026-09-18T15:00:00.000Z", 4), // 2026-09-18 local
      ],
      "America/New_York",
      NOW,
    );

    expect(groups.map((group) => group.label)).toEqual([
      "Today",
      "Yesterday",
      "2026-09-18",
    ]);
    expect(groups[0]?.events.map((event) => event.id)).toEqual([1, 2]);
  });

  it("keeps the endpoint's ordering rather than re-sorting", () => {
    const groups = groupActivityByDay(
      [
        at("2026-09-21T01:43:00.000Z", 1),
        at("2026-09-21T01:10:00.000Z", 2),
        at("2026-09-21T01:30:00.000Z", 3),
      ],
      "America/New_York",
      NOW,
    );

    expect(groups[0]?.events.map((event) => event.id)).toEqual([1, 2, 3]);
  });

  it("returns nothing for an empty page", () => {
    expect(groupActivityByDay([], "UTC", NOW)).toEqual([]);
  });

  it("falls back to the UTC day rather than throwing on a bad zone", () => {
    const groups = groupActivityByDay(
      [at("2026-09-21T01:43:00.000Z", 1)],
      "Not/AZone",
      NOW,
    );

    expect(groups[0]?.key).toBe("2026-09-21");
  });
});
