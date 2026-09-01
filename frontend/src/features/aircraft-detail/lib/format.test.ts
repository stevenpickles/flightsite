import { describe, expect, it } from "vitest";

import {
  cardinalFromDegrees,
  formatAltitude,
  formatDegreesWithCardinal,
  formatDistance,
  formatDurationShort,
  formatFlightLevel,
  formatMessageCount,
  formatOnGround,
  formatReceiverLocalDateTime,
  formatReceiverLocalTime,
  formatRelativeAge,
  formatRssi,
  formatSpeed,
  formatVerticalRate,
  isEmergencySquawk,
  msSinceLastSeen,
  verticalTrend,
} from "@/features/aircraft-detail/lib/format";

describe("formatFlightLevel", () => {
  it("renders hundreds of feet, zero-padded to three digits", () => {
    expect(formatFlightLevel(35000)).toBe("FL350");
    expect(formatFlightLevel(5000)).toBe("FL050");
  });
});

describe("formatAltitude", () => {
  it("renders Unknown-eligible null as null", () => {
    expect(formatAltitude(null, "aviation")).toBeNull();
  });

  it("shows feet in aviation mode below the flight-level threshold", () => {
    expect(formatAltitude(1250, "aviation")).toBe("1,250 ft");
  });

  it("prefixes a flight level at/above 18,000 ft in aviation mode", () => {
    expect(formatAltitude(35000, "aviation")).toBe("FL350 · 35,000 ft");
  });

  it("converts to meters in metric mode", () => {
    expect(formatAltitude(1000, "metric")).toBe("305 m");
  });

  it("still prefixes a flight level in metric mode (feet-based convention)", () => {
    expect(formatAltitude(24975, "metric")).toBe("FL250 · 7,612 m");
  });
});

describe("formatSpeed", () => {
  it("renders knots as-is in aviation mode", () => {
    expect(formatSpeed(450, "aviation")).toBe("450 kt");
  });

  it("converts to km/h in metric mode", () => {
    expect(formatSpeed(100, "metric")).toBe("185 km/h");
  });

  it("renders null as null", () => {
    expect(formatSpeed(null, "aviation")).toBeNull();
  });
});

describe("formatDistance", () => {
  it("renders nm with one decimal in aviation mode", () => {
    expect(formatDistance(18.4, "aviation")).toBe("18.4 nm");
  });

  it("converts to km in metric mode", () => {
    expect(formatDistance(10, "metric")).toBe("18.5 km");
  });
});

describe("verticalTrend", () => {
  it("reports climb above the noise floor", () => {
    expect(verticalTrend(640)).toBe("climb");
  });

  it("reports descend below the negative noise floor", () => {
    expect(verticalTrend(-640)).toBe("descend");
  });

  it("reports level within the noise floor", () => {
    expect(verticalTrend(0)).toBe("level");
    expect(verticalTrend(20)).toBe("level");
    expect(verticalTrend(-20)).toBe("level");
  });

  it("returns null for null input", () => {
    expect(verticalTrend(null)).toBeNull();
  });
});

describe("formatVerticalRate", () => {
  it("renders fpm with an explicit sign in aviation mode", () => {
    expect(formatVerticalRate(640, "aviation")).toBe("+640 fpm");
    expect(formatVerticalRate(-640, "aviation")).toBe("-640 fpm");
    expect(formatVerticalRate(0, "aviation")).toBe("0 fpm");
  });

  it("converts to m/s in metric mode", () => {
    expect(formatVerticalRate(600, "metric")).toBe("+3.0 m/s");
  });
});

describe("cardinalFromDegrees", () => {
  it.each([
    [0, "N"],
    [90, "E"],
    [180, "S"],
    [270, "W"],
    [173, "S"],
    [360, "N"],
    [22.5, "NNE"],
  ])("maps %s° to %s", (deg, expected) => {
    expect(cardinalFromDegrees(deg)).toBe(expected);
  });

  it("normalizes negative degrees", () => {
    expect(cardinalFromDegrees(-90)).toBe("W");
  });
});

describe("formatDegreesWithCardinal", () => {
  it("combines rounded degrees and cardinal", () => {
    expect(formatDegreesWithCardinal(173.2)).toBe("173° · S");
  });

  it("renders null as null", () => {
    expect(formatDegreesWithCardinal(null)).toBeNull();
  });
});

describe("formatRssi", () => {
  it("renders one decimal place with unit", () => {
    expect(formatRssi(-12.14)).toBe("-12.1 dBFS");
  });
});

describe("formatMessageCount", () => {
  it("adds thousands separators", () => {
    expect(formatMessageCount(4812)).toBe("4,812");
  });

  it("renders null as null", () => {
    expect(formatMessageCount(null)).toBeNull();
  });
});

describe("formatOnGround", () => {
  it("renders Yes/No, and null as null (never a guess)", () => {
    expect(formatOnGround(true)).toBe("Yes");
    expect(formatOnGround(false)).toBe("No");
    expect(formatOnGround(null)).toBeNull();
  });
});

describe("isEmergencySquawk", () => {
  it("recognizes 7500/7600/7700", () => {
    expect(isEmergencySquawk("7500")).toBe(true);
    expect(isEmergencySquawk("7600")).toBe(true);
    expect(isEmergencySquawk("7700")).toBe(true);
  });

  it("rejects ordinary codes and null", () => {
    expect(isEmergencySquawk("1200")).toBe(false);
    expect(isEmergencySquawk(null)).toBe(false);
  });
});

describe("msSinceLastSeen", () => {
  it("computes elapsed time", () => {
    const now = Date.parse("2026-08-31T00:00:10Z");
    expect(msSinceLastSeen("2026-08-31T00:00:00Z", now)).toBe(10000);
  });

  it("clamps clock skew to zero instead of going negative", () => {
    const now = Date.parse("2026-08-31T00:00:00Z");
    expect(msSinceLastSeen("2026-08-31T00:00:05Z", now)).toBe(0);
  });

  it("returns zero for an unparseable instant", () => {
    expect(msSinceLastSeen("not-a-date", Date.now())).toBe(0);
  });
});

describe("formatRelativeAge", () => {
  it.each([
    [500, "just now"],
    [12000, "12s ago"],
    [59000, "59s ago"],
    [60000, "1m ago"],
    [125000, "2m ago"],
    [3600000, "1h ago"],
    [3900000, "1h 5m ago"],
    [90000000, "1d ago"],
  ])("formats %sms as %s", (ms, expected) => {
    expect(formatRelativeAge(ms)).toBe(expected);
  });
});

describe("formatReceiverLocalTime", () => {
  it("formats an instant in the given IANA timezone", () => {
    const result = formatReceiverLocalTime(
      "2026-08-31T14:03:22Z",
      "America/Los_Angeles",
    );
    // PDT is UTC-7 in August.
    expect(result).toBe("07:03:22");
  });

  it("falls back to the ISO string for an unparseable instant", () => {
    expect(formatReceiverLocalTime("not-a-date", "UTC")).toBe("not-a-date");
  });
});

describe("formatReceiverLocalDateTime", () => {
  it("formats an instant with both date and time in the given IANA timezone", () => {
    const result = formatReceiverLocalDateTime(
      "2026-04-02T18:11:09Z",
      "America/Los_Angeles",
    );
    // PDT is UTC-7 in April.
    expect(result).toBe("2026-04-02 11:11");
  });

  it("crosses a day boundary correctly for a timezone behind UTC", () => {
    const result = formatReceiverLocalDateTime(
      "2026-01-01T02:00:00Z",
      "America/Los_Angeles",
    );
    // PST is UTC-8 in January.
    expect(result).toBe("2025-12-31 18:00");
  });

  it("falls back to the ISO string for an unparseable instant", () => {
    expect(formatReceiverLocalDateTime("not-a-date", "UTC")).toBe("not-a-date");
  });
});

describe("formatDurationShort", () => {
  it("renders seconds only under a minute", () => {
    expect(formatDurationShort(45000)).toBe("45s");
  });

  it("renders minutes and seconds at/above a minute", () => {
    expect(formatDurationShort(192000)).toBe("3m 12s");
  });

  it("clamps a negative span to zero", () => {
    expect(formatDurationShort(-500)).toBe("0s");
  });
});
