import { describe, expect, it } from "vitest";

import {
  formatAgeAgo,
  formatBytes,
  formatPercent,
  humanizeKey,
  NOT_AVAILABLE,
} from "@/features/health/lib/format";

describe("formatBytes", () => {
  it("renders bytes below a kilobyte without a unit prefix", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(999)).toBe("999 B");
  });

  it("uses binary multiples so it agrees with df and ls -lh", () => {
    expect(formatBytes(1024)).toBe("1.0 KB");
    expect(formatBytes(1024 * 1024)).toBe("1.0 MB");
    expect(formatBytes(1024 * 1024 * 1024)).toBe("1.0 GB");
  });

  it("keeps one decimal below ten and drops it above", () => {
    expect(formatBytes(1.4 * 1024 * 1024 * 1024)).toBe("1.4 GB");
    expect(formatBytes(42 * 1024 * 1024)).toBe("42 MB");
  });

  it("renders unknown and impossible sizes as the placeholder", () => {
    expect(formatBytes(null)).toBe(NOT_AVAILABLE);
    expect(formatBytes(-1)).toBe(NOT_AVAILABLE);
    expect(formatBytes(Number.NaN)).toBe(NOT_AVAILABLE);
  });

  it("does not run past the largest unit it knows", () => {
    expect(formatBytes(1024 ** 6)).toContain("PB");
  });
});

describe("formatAgeAgo", () => {
  it("describes a very recent instant in words", () => {
    expect(formatAgeAgo(0)).toBe("just now");
    expect(formatAgeAgo(9)).toBe("just now");
  });

  it("steps up through seconds, minutes, hours and days", () => {
    expect(formatAgeAgo(45)).toBe("45s ago");
    expect(formatAgeAgo(120)).toBe("2m ago");
    expect(formatAgeAgo(7200)).toBe("2h ago");
    expect(formatAgeAgo(3 * 86400)).toBe("3d ago");
  });

  it("renders an unknown age as the placeholder", () => {
    expect(formatAgeAgo(null)).toBe(NOT_AVAILABLE);
  });
});

describe("formatPercent", () => {
  it("renders a ratio with one decimal", () => {
    expect(formatPercent(0.031)).toBe("3.1%");
    expect(formatPercent(0)).toBe("0.0%");
  });

  it("renders an unknown ratio as the placeholder", () => {
    expect(formatPercent(null)).toBe(NOT_AVAILABLE);
  });
});

describe("humanizeKey", () => {
  it("turns a wire key into a readable label", () => {
    expect(humanizeKey("sighting_tracks")).toBe("Sighting tracks");
    expect(humanizeKey("aircraft")).toBe("Aircraft");
  });
});
