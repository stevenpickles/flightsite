import { describe, expect, it } from "vitest";

import {
  CLOSURE_REASON_INFO,
  describeClosureReason,
  formatSightingDuration,
} from "@/features/sightings/lib/format";

describe("formatSightingDuration", () => {
  it("formats seconds only under a minute", () => {
    expect(formatSightingDuration(45)).toBe("45s");
    expect(formatSightingDuration(0)).toBe("0s");
  });

  it("formats minutes and seconds under an hour", () => {
    expect(formatSightingDuration(2385)).toBe("39m 45s");
  });

  it("formats hours and minutes under a day", () => {
    expect(formatSightingDuration(3600)).toBe("1h 00m");
    expect(formatSightingDuration(3900)).toBe("1h 05m");
  });

  it("formats days and hours beyond a day", () => {
    expect(formatSightingDuration(90_000)).toBe("1d 1h");
  });

  it("clamps a negative duration to zero", () => {
    expect(formatSightingDuration(-5)).toBe("0s");
  });
});

describe("describeClosureReason", () => {
  it("returns null for a null reason", () => {
    expect(describeClosureReason(null)).toBeNull();
  });

  it("describes every documented closure reason in plain language", () => {
    for (const reason of Object.keys(
      CLOSURE_REASON_INFO,
    ) as (keyof typeof CLOSURE_REASON_INFO)[]) {
      const info = describeClosureReason(reason);
      expect(info?.label.length).toBeGreaterThan(0);
      expect(info?.description.length).toBeGreaterThan(0);
    }
  });

  it("distinguishes gap_timeout from shutdown_recovery in words", () => {
    expect(describeClosureReason("gap_timeout")?.description).toMatch(
      /absence gap/i,
    );
    expect(describeClosureReason("shutdown_recovery")?.description).toMatch(
      /restart/i,
    );
  });
});
