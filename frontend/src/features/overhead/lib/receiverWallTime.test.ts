import { describe, expect, it } from "vitest";

import {
  toWallTimeInput,
  wallTimeInputToIso,
} from "@/features/overhead/lib/receiverWallTime";

describe("receiver wall time", () => {
  it("shows an instant on the receiver's clock, not the browser's", () => {
    expect(
      toWallTimeInput("2026-08-30T22:10:30.000Z", "America/New_York"),
    ).toBe("2026-08-30T18:10");
    expect(toWallTimeInput("2026-08-30T22:10:30.000Z", "Asia/Tokyo")).toBe(
      "2026-08-31T07:10",
    );
    expect(toWallTimeInput("2026-08-30T22:10:30.000Z", "UTC")).toBe(
      "2026-08-30T22:10",
    );
  });

  it("reads a picked wall time in the receiver's zone as a UTC instant", () => {
    expect(wallTimeInputToIso("2026-08-30T18:10", "America/New_York")).toBe(
      "2026-08-30T22:10:00.000Z",
    );
    expect(wallTimeInputToIso("2026-01-15T18:10", "America/New_York")).toBe(
      "2026-01-15T23:10:00.000Z",
    );
    expect(wallTimeInputToIso("2026-08-31T07:10", "Asia/Tokyo")).toBe(
      "2026-08-30T22:10:00.000Z",
    );
  });

  it("round-trips across a DST change", () => {
    for (const iso of [
      "2026-03-08T06:59:00.000Z",
      "2026-03-08T07:01:00.000Z",
      "2026-11-01T05:30:00.000Z",
    ]) {
      const wall = toWallTimeInput(iso, "America/New_York");
      expect(wallTimeInputToIso(wall, "America/New_York")).toBe(iso);
    }
  });

  it("rejects an empty or malformed value", () => {
    expect(wallTimeInputToIso("", "UTC")).toBeNull();
    expect(wallTimeInputToIso("2026-08-30", "UTC")).toBeNull();
    expect(wallTimeInputToIso("not a time", "UTC")).toBeNull();
  });

  it("falls back to UTC for a zone Intl does not know", () => {
    expect(wallTimeInputToIso("2026-08-30T18:10", "Not/AZone")).toBe(
      "2026-08-30T18:10:00.000Z",
    );
    expect(toWallTimeInput("2026-08-30T18:10:00.000Z", "Not/AZone")).toBe(
      "2026-08-30T18:10",
    );
  });
});
