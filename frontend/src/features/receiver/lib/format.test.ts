import { describe, expect, it } from "vitest";

import {
  cardinalFromDegrees,
  distanceAxisValue,
  distanceUnitLabel,
  formatCount,
  formatDb,
  formatDistance,
  formatDurationCompact,
  formatRatePerSec,
  formatReceiverLocalDate,
  formatReceiverLocalDateTime,
  formatReceiverLocalTime,
} from "@/features/receiver/lib/format";

describe("formatDistance", () => {
  it("renders nm as-is in aviation units", () => {
    expect(formatDistance(87.34, "aviation")).toBe("87.3 nm");
  });

  it("converts to km in metric units", () => {
    expect(formatDistance(87.34, "metric")).toBe("161.8 km");
  });

  it("renders null as null (caller's job to render a placeholder)", () => {
    expect(formatDistance(null, "aviation")).toBeNull();
  });
});

describe("distanceAxisValue / distanceUnitLabel", () => {
  it("converts and labels consistently with formatDistance", () => {
    expect(distanceAxisValue(100, "aviation")).toBe(100);
    expect(distanceAxisValue(100, "metric")).toBeCloseTo(185.2, 1);
    expect(distanceUnitLabel("aviation")).toBe("nm");
    expect(distanceUnitLabel("metric")).toBe("km");
  });
});

describe("formatCount", () => {
  it("localizes thousands separators", () => {
    expect(formatCount(12345)).toBe("12,345");
  });

  it("renders a placeholder for null", () => {
    expect(formatCount(null)).toBe("—");
  });
});

describe("formatRatePerSec", () => {
  it("renders one decimal place with a unit/s suffix", () => {
    expect(formatRatePerSec(12.34, "msg")).toBe("12.3 msg/s");
  });

  it("renders a placeholder for null", () => {
    expect(formatRatePerSec(null, "msg")).toBe("—");
  });
});

describe("formatDb", () => {
  it("renders one decimal place with a dB suffix", () => {
    expect(formatDb(-24.567)).toBe("-24.6 dB");
  });

  it("renders a placeholder for null", () => {
    expect(formatDb(null)).toBe("—");
  });
});

describe("formatDurationCompact", () => {
  it("renders days and hours for a multi-day span", () => {
    expect(formatDurationCompact(3 * 86400 + 4 * 3600)).toBe("3d 4h");
  });

  it("drops the hours when they are zero", () => {
    expect(formatDurationCompact(3 * 86400)).toBe("3d");
  });

  it("renders hours and minutes under a day", () => {
    expect(formatDurationCompact(2 * 3600 + 15 * 60)).toBe("2h 15m");
  });

  it("renders minutes under an hour", () => {
    expect(formatDurationCompact(5 * 60)).toBe("5m");
  });

  it("renders seconds under a minute", () => {
    expect(formatDurationCompact(48)).toBe("48s");
  });

  it("renders a placeholder for null or negative input", () => {
    expect(formatDurationCompact(null)).toBe("—");
    expect(formatDurationCompact(-1)).toBe("—");
  });
});

describe("receiver-local time formatting", () => {
  const iso = "2026-08-30T14:03:22.000Z";

  it("formats a time-of-day in the receiver's timezone", () => {
    expect(formatReceiverLocalTime(iso, "UTC")).toBe("14:03");
  });

  it("formats a full local date and time", () => {
    expect(formatReceiverLocalDateTime(iso, "UTC")).toBe("2026-08-30 14:03");
  });

  it("formats a calendar date", () => {
    expect(formatReceiverLocalDate(iso, "UTC")).toBe("08/30/2026");
  });

  it("renders a different wall-clock time in a non-UTC timezone", () => {
    // 14:03 UTC is 07:03 the same day in America/Los_Angeles (PDT, UTC-7 in August).
    expect(formatReceiverLocalTime(iso, "America/Los_Angeles")).toBe("07:03");
  });

  it("falls back to the raw ISO string for an unparseable instant", () => {
    expect(formatReceiverLocalTime("not-a-date", "UTC")).toBe("not-a-date");
  });
});

describe("cardinalFromDegrees", () => {
  it("maps the four cardinal points", () => {
    expect(cardinalFromDegrees(0)).toBe("N");
    expect(cardinalFromDegrees(90)).toBe("E");
    expect(cardinalFromDegrees(180)).toBe("S");
    expect(cardinalFromDegrees(270)).toBe("W");
  });

  it("normalizes a bearing outside 0-360", () => {
    expect(cardinalFromDegrees(370)).toBe("N");
    expect(cardinalFromDegrees(-10)).toBe("N");
  });
});
