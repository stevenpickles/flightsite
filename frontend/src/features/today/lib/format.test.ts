import { describe, expect, it } from "vitest";

import {
  formatCount,
  formatDistance,
  formatHourRange,
} from "@/features/today/lib/format";

describe("formatCount", () => {
  it("formats a plain count with locale grouping", () => {
    expect(formatCount(0)).toBe("0");
    expect(formatCount(1234)).toBe("1,234");
  });
});

describe("formatDistance", () => {
  it("renders nautical miles in aviation units", () => {
    expect(formatDistance(187.44, "aviation")).toBe("187.4 nm");
  });

  it("converts to kilometers in metric units", () => {
    expect(formatDistance(187.44, "metric")).toBe("347.1 km");
  });

  it("passes null through rather than formatting a placeholder", () => {
    expect(formatDistance(null, "aviation")).toBeNull();
  });
});

describe("formatHourRange", () => {
  it("renders an hour as the receiver-local clock range it covers", () => {
    expect(formatHourRange(14)).toBe("14:00–15:00");
  });

  it("zero-pads single-digit hours", () => {
    expect(formatHourRange(9)).toBe("09:00–10:00");
  });

  it("wraps the last hour of the day into 00:00", () => {
    expect(formatHourRange(23)).toBe("23:00–00:00");
  });

  it("reads as 'No data yet' rather than a blank tile", () => {
    expect(formatHourRange(null)).toBe("No data yet");
  });
});
