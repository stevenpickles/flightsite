import { describe, expect, it } from "vitest";

import {
  convertDistance,
  distanceUnitLabel,
  escapeHtml,
  formatCompactNumber,
  formatSightings,
  formatWindowLabel,
  humanizeSlug,
  tooltipLines,
  truncateLabel,
} from "@/features/analytics/lib/format";

describe("distanceUnitLabel", () => {
  it("returns nm for aviation and km for metric", () => {
    expect(distanceUnitLabel("aviation")).toBe("nm");
    expect(distanceUnitLabel("metric")).toBe("km");
  });
});

describe("convertDistance", () => {
  it("passes nm through unchanged for aviation units", () => {
    expect(convertDistance(141.8, "aviation")).toBe(141.8);
  });

  it("converts nm to km for metric units", () => {
    expect(convertDistance(100, "metric")).toBeCloseTo(185.2, 1);
  });
});

describe("formatCompactNumber", () => {
  it("compacts large numbers", () => {
    expect(formatCompactNumber(1200)).toMatch(/1\.2K/i);
  });

  it("leaves small numbers as-is", () => {
    expect(formatCompactNumber(48)).toBe("48");
  });
});

describe("formatWindowLabel", () => {
  it("renders a single date when the window is one day", () => {
    const label = formatWindowLabel({
      preset: "today",
      from: "2026-08-31T00:00:00.000Z",
      to: "2026-09-01T00:00:00.000Z",
      first_day: "2026-08-31",
      last_day: "2026-08-31",
      timezone: "America/Los_Angeles",
    });
    expect(label).toContain("Aug 31, 2026");
    expect(label).toContain("America/Los_Angeles");
    expect(label).not.toContain("–");
  });

  it("renders a range when the window spans multiple days", () => {
    const label = formatWindowLabel({
      preset: "7d",
      from: "2026-08-25T00:00:00.000Z",
      to: "2026-09-01T00:00:00.000Z",
      first_day: "2026-08-25",
      last_day: "2026-08-31",
      timezone: "UTC",
    });
    expect(label).toContain("Aug 25, 2026");
    expect(label).toContain("Aug 31, 2026");
    expect(label).toContain("–");
  });

  it("falls back to the raw string for an unparseable day", () => {
    const label = formatWindowLabel({
      preset: null,
      from: "x",
      to: "y",
      first_day: "not-a-date",
      last_day: "not-a-date",
      timezone: "UTC",
    });
    expect(label).toContain("not-a-date");
  });
});

describe("humanizeSlug", () => {
  it("replaces underscores and capitalizes the first letter", () => {
    expect(humanizeSlug("military_transport")).toBe("Military transport");
  });

  it("passes a single word through with capitalization", () => {
    expect(humanizeSlug("civilian")).toBe("Civilian");
  });
});

describe("truncateLabel", () => {
  it("leaves text within the limit untouched", () => {
    expect(truncateLabel("Boeing 737-800", 24)).toBe("Boeing 737-800");
  });

  it("cuts longer text to the limit with an ellipsis, without a dangling space", () => {
    const cut = truncateLabel("Lockheed C-130J Super Hercules", 16);
    expect(cut).toBe("Lockheed C-130J…");
    expect(cut.length).toBeLessThanOrEqual(16);
  });
});

describe("escapeHtml", () => {
  it("escapes the characters that would otherwise become markup", () => {
    expect(escapeHtml(`<b>"Ma&Pa's"</b>`)).toBe(
      "&lt;b&gt;&quot;Ma&amp;Pa&#39;s&quot;&lt;/b&gt;",
    );
  });
});

describe("tooltipLines", () => {
  it("bolds the first line, drops empty ones, and escapes every line", () => {
    expect(
      tooltipLines(["N302DN", null, "", "Boeing <737>", "8 sightings"]),
    ).toBe("<strong>N302DN</strong><br/>Boeing &lt;737&gt;<br/>8 sightings");
  });

  it("returns an empty string when nothing is known", () => {
    expect(tooltipLines([null, ""])).toBe("");
  });
});

describe("formatSightings", () => {
  it("pluralizes", () => {
    expect(formatSightings(1)).toBe("1 sighting");
    expect(formatSightings(12)).toBe("12 sightings");
  });
});
